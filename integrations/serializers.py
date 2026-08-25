from rest_framework import serializers

from integrations.models import Commit, CommitFile, GitAccount, MergeRequest, Repository
from integrations.services.languages import calculate_language_stats


class GitAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = GitAccount
        fields = (
            'id',
            'provider',
            'username',
            'avatar_url',
            'profile_url',
            'connected_at',
            'last_synced_at',
        )
        read_only_fields = fields


class RepositorySerializer(serializers.ModelSerializer):
    provider = serializers.CharField(source='git_account.provider', read_only=True)

    class Meta:
        model = Repository
        fields = (
            'id',
            'provider',
            'name',
            'full_name',
            'description',
            'url',
            'default_branch',
            'is_private',
            'last_synced_at',
        )
        read_only_fields = fields


class CommitFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommitFile
        fields = ('id', 'filename', 'status', 'additions', 'deletions', 'patch')
        read_only_fields = fields


class CommitSerializer(serializers.ModelSerializer):
    repository = serializers.CharField(source='repository.full_name', read_only=True)
    reviewed_by = serializers.SerializerMethodField()
    files = CommitFileSerializer(many=True, read_only=True)
    language_stats = serializers.SerializerMethodField()

    def get_reviewed_by(self, commit):
        return commit.reviewed_by.email if commit.reviewed_by else None

    def get_language_stats(self, commit):
        return calculate_language_stats(commit.files.all())

    class Meta:
        model = Commit
        fields = (
            'id',
            'repository',
            'sha',
            'message',
            'author_name',
            'author_email',
            'authored_at',
            'url',
            'additions',
            'deletions',
            'status',
            'reviewed_by',
            'reviewed_at',
            'review_notes',
            'files',
            'language_stats',
        )
        read_only_fields = fields


class CommitReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Commit
        fields = ('status', 'review_notes')

    def validate_status(self, value):
        if value not in (Commit.Status.APPROVED, Commit.Status.REJECTED):
            raise serializers.ValidationError('status must be "approved" or "rejected"')
        return value


class MergeRequestSerializer(serializers.ModelSerializer):
    repository = serializers.CharField(source='repository.full_name', read_only=True)
    reviewed_by = serializers.SerializerMethodField()

    def get_reviewed_by(self, merge_request):
        return merge_request.reviewed_by.email if merge_request.reviewed_by else None

    class Meta:
        model = MergeRequest
        fields = (
            'id',
            'repository',
            'provider_mr_id',
            'title',
            'description',
            'author_name',
            'source_branch',
            'target_branch',
            'url',
            'provider_state',
            'provider_created_at',
            'provider_updated_at',
            'status',
            'reviewed_by',
            'reviewed_at',
            'review_notes',
        )
        read_only_fields = fields


class MergeRequestReviewSerializer(serializers.Serializer):
    """Not a ModelSerializer: 'action' drives provider-side merge/close calls and isn't
    a model field itself — it maps to both `status` and `provider_state` in the view."""

    action = serializers.ChoiceField(choices=('merge', 'reject', 'close'))
    review_notes = serializers.CharField(required=False, allow_blank=True, default='')
