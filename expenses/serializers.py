from rest_framework import serializers

from .models import Category, Expense


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "description"]


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        # 'category' field was previously misspelled as 'catgory'
        fields = ["id", "title", "amount", "currency", "category", "date", "notes"]
