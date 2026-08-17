from pathlib import Path


def video_dir_width(video_count: int) -> int:
    return max(2, len(str(video_count)))


def format_video_dir(index: int, video_count: int) -> str:
    return f"{index:0{video_dir_width(video_count)}d}"


def create_run_skeleton(run_dir: Path, video_count: int) -> None:
    (run_dir / "shared").mkdir(parents=True, exist_ok=True)
    (run_dir / "instructions").mkdir(exist_ok=True)
    for index in range(1, video_count + 1):
        video = run_dir / format_video_dir(index, video_count)
        (video / ".steps").mkdir(parents=True, exist_ok=True)
        (video / "artifacts").mkdir(exist_ok=True)
