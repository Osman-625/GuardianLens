# The extension's side panel shows only the LAST suggested check, as the most protective one. This
# pins that contract on the API side, so reordering the list cannot silently change the advice.
from api.services.orchestrator import SUGGESTED_CHECKS


def test_last_suggested_check_is_the_independent_seller_check() -> None:
    assert "Semak Mule" in SUGGESTED_CHECKS[-1]
