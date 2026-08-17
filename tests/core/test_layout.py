from pathlib import Path

from app.core.layout import create_run_skeleton


def test_skeleton_creates_shared_instructions_and_padded_videos(tmp_path: Path) -> None:
    run_dir = tmp_path / "news-explainer" / "20260810-143022"
    create_run_skeleton(run_dir, video_count=2)
    assert (run_dir / "shared").is_dir()
    assert (run_dir / "instructions").is_dir()
    assert list((run_dir / "instructions").iterdir()) == []
    for index in ("01", "02"):
        video = run_dir / index
        assert (video / ".steps").is_dir()
        assert (video / "artifacts").is_dir()
        assert not (video / "context.json").exists()
        assert not (video / "video.json").exists()
        assert not (video / "final.mp4").exists()
    assert not (run_dir / "1").exists()
    names = sorted(path.name for path in run_dir.iterdir() if path.name.isdigit())
    assert names == ["01", "02"]


def test_skeleton_widens_padding_above_99_videos(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    create_run_skeleton(run_dir, video_count=100)
    assert (run_dir / "001" / ".steps").is_dir()
    assert (run_dir / "100" / "artifacts").is_dir()
    assert not (run_dir / "01").exists()
    assert not (run_dir / "1").exists()
