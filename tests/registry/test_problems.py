from app.registry.problems import Problem, ProblemCode


def test_problem_carries_named_code_message_and_severity() -> None:
    problem = Problem(
        code=ProblemCode.SCHEMA_INVALID,
        message="output.aspect is not a permitted value",
        severity="error",
    )
    assert problem.code == ProblemCode.SCHEMA_INVALID
    assert problem.code.value == "schema_invalid"
    assert problem.severity == "error"


def test_stage1_codes_do_not_reject_unknown_recovery_actions() -> None:
    assert "recovery_unknown_action" not in {code.value for code in ProblemCode}
