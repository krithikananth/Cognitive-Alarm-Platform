from django.shortcuts import render
from django.http import JsonResponse
from .models import Challenge

def challenge_list(request):
    data = list(
        Challenge.objects.values(
            'id',
            'question_type',
            'question'
        )
    )

    return JsonResponse(data, safe=False)

def challenge_page(request):
    questions = list(Challenge.objects.all())

    index = int(request.GET.get('index', 0))

    if index >= len(questions):
        index = 0

    question = questions[index]
    message = ""

    if request.method == "POST":
        user_answer = request.POST.get("answer", "").strip()

        if user_answer.lower() == question.answer.lower():
            message = "✅ Correct Answer!"
        else:
            message = f"❌ Wrong Answer! Correct Answer: {question.answer}"

    return render(request, "challenge/challenge.html", {
        "question": question,
        "index": index,
        "next_index": index + 1,
        "message": message,
    })