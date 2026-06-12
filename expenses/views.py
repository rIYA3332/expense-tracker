from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Sum
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
import requests
from datetime import date
import csv
from django.http import HttpResponse

from .models import Category, Expense
from .serializers import CategorySerializer, ExpenseSerializer


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    username = request.data.get("username")
    password = request.data.get("password")

    if not username or not password:
        return Response(
            {"error": "Username and password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if User.objects.filter(username=username).exists():
        return Response(
            {"error": "Username already exists."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = User.objects.create_user(username=username, password=password)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    username = request.data.get("username")
    password = request.data.get("password")

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return Response(
            {"error": "Invalid credentials."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.check_password(password):
        return Response(
            {"error": "Invalid credentials."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def category_list(request):
    if request.method == "GET":
        # Only return categories belonging to the logged-in user
        categories = Category.objects.filter(user=request.user)
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)

    serializer = CategorySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    # Assign the logged-in user as the owner
    serializer.save(user=request.user)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def expense_list(request):
    if request.method == "GET":
        # Only return expenses belonging to the logged-in user
        expenses = Expense.objects.filter(user=request.user)

        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        # Use gte (greater than or equal) to make start_date inclusive
        if start_date:
            expenses = expenses.filter(date__gte=start_date)
        if end_date:
            expenses = expenses.filter(date__lte=end_date)

        serializer = ExpenseSerializer(expenses, many=True)
        return Response(serializer.data)

    serializer = ExpenseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    # Assign the logged-in user as the owner
    expense = serializer.save(user=request.user)

    # Check if this expense pushes the category over its monthly limit
    category = expense.category
    if category.monthly_limit is not None:
        now = date.today()
        # Calculate month-to-date total for this category
        month_total = Expense.objects.filter(
            user=request.user,
            category=category,
            date__year=now.year,
            date__month=now.month,
        ).aggregate(total=Sum("amount"))["total"] or 0

        if month_total > category.monthly_limit:
            send_budget_alert(category, float(month_total), float(category.monthly_limit))

    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def expense_detail(request, pk):
    try:
        # Only allow access to the logged-in user's own expenses
        expense = Expense.objects.get(pk=pk, user=request.user)
    except Expense.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        serializer = ExpenseSerializer(expense)
        return Response(serializer.data)

    if request.method == "PUT":
        serializer = ExpenseSerializer(expense, data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_expense = serializer.save()

        # Check budget limit on update as well
        category = updated_expense.category
        if category.monthly_limit is not None:
            now = date.today()
            month_total = Expense.objects.filter(
                user=request.user,
                category=category,
                date__year=now.year,
                date__month=now.month,
            ).aggregate(total=Sum("amount"))["total"] or 0

            if month_total > category.monthly_limit:
                send_budget_alert(category, float(month_total), float(category.monthly_limit))

        return Response(serializer.data)

    expense.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


def get_exchange_rate(from_currency, to_currency):
    """Fetch exchange rate from open.er-api.com (no API key required)."""
    if from_currency == to_currency:
        return 1.0, date.today().isoformat()
    try:
        url = f"https://open.er-api.com/v6/latest/{from_currency}"
        response = requests.get(url, timeout=5)
        data = response.json()
        if data.get("result") == "success":
            rate = data["rates"].get(to_currency)
            as_of = data.get("time_last_update_utc", date.today().isoformat())[:10]
            return rate, as_of
    except Exception:
        pass
    return None, None

def send_budget_alert(category, total_spent, monthly_limit):
    """Send a budget alert to Discord when a category exceeds its monthly limit."""
    bot_token = settings.BOT_TOKEN
    if not bot_token:
        return

    now = date.today()
    month_name = now.strftime("%B %Y")

    message = (
        f" Budget alert: \"{category.name}\" is over its monthly limit.\n"
        f"Spent {total_spent:.2f} / {monthly_limit:.2f} {settings.BASE_CURRENCY} for {month_name}."
    )

    try:
        # Discord webhook — just POST with content field
        requests.post(bot_token, json={"content": message}, timeout=5)
    except Exception:
        pass

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def expense_summary(request):
    base_currency = settings.BASE_CURRENCY

    # Get all expenses for the logged-in user grouped by category
    expenses = Expense.objects.filter(user=request.user)
    
    # Group expenses by category
    category_expenses = {}
    for expense in expenses:
        cat_name = expense.category.name
        if cat_name not in category_expenses:
            category_expenses[cat_name] = []
        category_expenses[cat_name].append(expense)

    categories_summary = []
    for cat_name, exps in category_expenses.items():
        total_in_base = 0
        rate_used = None
        as_of = None

        for expense in exps:
            if expense.currency == base_currency:
                total_in_base += float(expense.amount)
                rate_used = "1.0"
                as_of = date.today().isoformat()
            else:
                # Fetch exchange rate for this currency
                rate, rate_date = get_exchange_rate(expense.currency, base_currency)
                if rate:
                    total_in_base += float(expense.amount) * rate
                    rate_used = str(round(rate, 4))
                    as_of = rate_date
                else:
                    # If rate fetch fails, use amount as-is
                    total_in_base += float(expense.amount)

        categories_summary.append({
            "category": cat_name,
            "total": str(round(total_in_base, 2)),
            "rate": rate_used,
            "as_of": as_of,
        })

    return Response({
        "base_currency": base_currency,
        "categories": categories_summary,
    })

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def expense_csv_export(request):
    """Export all expenses for the logged-in user as a CSV file."""
    expenses = Expense.objects.filter(user=request.user).order_by("date")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="expenses.csv"'

    writer = csv.writer(response)
    # Write header row
    writer.writerow(["ID", "Title", "Amount", "Currency", "Category", "Date", "Notes"])

    # Write expense rows
    for expense in expenses:
        writer.writerow([
            expense.id,
            expense.title,
            expense.amount,
            expense.currency,
            expense.category.name,
            expense.date,
            expense.notes,
        ])

    return response