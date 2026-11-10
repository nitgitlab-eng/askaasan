from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import AnswerFeedback, Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "citations", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "kind", "title", "document", "updated_at"]


@api_view(["GET"])
def conversations(request):
    qs = Conversation.objects.filter(user=request.user)[:50]
    return Response(ConversationSerializer(qs, many=True).data)


@api_view(["GET", "DELETE"])
def conversation_detail(request, pk):
    conv = Conversation.objects.filter(user=request.user, pk=pk).first()
    if not conv:
        return Response(status=404)
    if request.method == "DELETE":
        conv.delete()
        return Response(status=204)
    msgs = MessageSerializer(conv.messages.all(), many=True).data
    mine = dict(
        AnswerFeedback.objects.filter(
            user=request.user, kind="message", object_id__in=[m["id"] for m in msgs]
        ).values_list("object_id", "rating")
    )
    return Response(
        {
            **ConversationSerializer(conv).data,
            "messages": [{**m, "my_rating": mine.get(m["id"], 0)} for m in msgs],
        }
    )
