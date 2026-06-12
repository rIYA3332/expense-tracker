from django.contrib.auth.models import User
from django.db.models import Sum
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

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
    serializer.save(user=request.user)
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
        serializer.save()
        return Response(serializer.data)

    expense.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def expense_summary(request):
    # Only summarize expenses belonging to the logged-in user
    summary = (
        Expense.objects.filter(user=request.user)
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("category__name")
    )
    return Response(list(summary))