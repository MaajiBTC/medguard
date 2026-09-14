from rest_framework import serializers


class EnrollFingerprintSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField()
    image = serializers.ImageField()


class IdentifyFingerprintSerializer(serializers.Serializer):
    image = serializers.ImageField()
