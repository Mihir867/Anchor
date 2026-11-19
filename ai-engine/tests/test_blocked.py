"""Bot-protection interstitials are recognised; ordinary pages are not."""
from anchor.crawl import blocked_reason


def test_vercel_checkpoint_is_blocked():
    assert blocked_reason("Vercel Security Checkpoint", "We're verifying your browser Website owner? Click here to fix")


def test_cloudflare_challenge_is_blocked():
    assert blocked_reason("Just a moment...", "Verifying you are human. This may take a few seconds.")


def test_normal_page_is_not_blocked():
    copy = "DevRev joins the OpenAI Marketplace launch. " * 50
    assert blocked_reason("DevRev | The AI platform with Native Shared Memory", copy) is None


def test_long_page_mentioning_access_denied_is_not_blocked():
    copy = "Fix 'access denied' errors in minutes with our IAM toolkit. " + "Real product copy. " * 400
    assert blocked_reason("IAM toolkit", copy) is None
