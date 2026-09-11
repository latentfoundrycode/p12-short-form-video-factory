def run(ctx) -> None:
    # Mimics finalize's §5.8 self-review event: all check results, then the result.
    ctx.emit(
        {
            "t": "self_review",
            "passed": True,
            "structural": {
                "duration_s": 30.0,
                "width": 1080,
                "height": 1920,
                "has_audio": True,
                "has_captions": True,
            },
            "content": {
                "black": False,
                "silent": False,
                "clipping": False,
                "slideshow": False,
                "audio_mean_dbfs": -18.0,
                "audio_peak_dbfs": -1.5,
                "motion_score": 0.05,
            },
            "composition": {"checked": 1, "violations": []},
            "failures": [],
        }
    )
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "self-review stub"})
