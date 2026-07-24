from django.db import models

class Challenge(models.Model):

    QUESTION_TYPES = [
        ('Math', 'Math'),
        ('Logic', 'Logic'),
        ('Memory', 'Memory'),
        ('Riddle', 'Riddle'),
        ('Word', 'Word'),
    ]

    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    question = models.TextField()
    answer = models.CharField(max_length=200)

    def __str__(self):
        return self.question