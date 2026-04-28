"""Shared test fixtures."""
import os
import pytest

# Set env vars before any alfred module is imported
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("VOYAGE_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("WEBHOOK_URL", "https://test.railway.app")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("JOBS_SECRET", "test-jobs-secret")
os.environ.setdefault("RESEND_API_KEY", "re_test_key")
os.environ.setdefault("CALENDAR_SENDER_EMAIL", "test@example.com")
