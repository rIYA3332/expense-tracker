from django.urls import path

from . import views

urlpatterns = [
    path("auth/register/", views.register, name="register"),
    path("auth/login/", views.login, name="login"),
    path("categories/", views.category_list, name="category-list"),
    path("expenses/", views.expense_list, name="expense-list"),
    path("expenses/summary/", views.expense_summary, name="expense-summary"),
    path("expenses/export/csv/", views.expense_csv_export, name="expense-csv-export"),
    path("expenses/<pk>/", views.expense_detail, name="expense-detail"),
]
