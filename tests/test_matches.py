from app.core.constants import ResultChoice
from app.services.matches import resolve_result_reports


def test_result_resolution_waits_for_second_player() -> None:
    assert resolve_result_reports([ResultChoice.WIN, None]) == "waiting"


def test_opposite_results_have_winner() -> None:
    assert resolve_result_reports([ResultChoice.WIN, ResultChoice.LOSS]) == "winner"


def test_equal_results_create_dispute() -> None:
    assert resolve_result_reports([ResultChoice.WIN, ResultChoice.WIN]) == "dispute"
    assert resolve_result_reports([ResultChoice.LOSS, ResultChoice.LOSS]) == "dispute"

