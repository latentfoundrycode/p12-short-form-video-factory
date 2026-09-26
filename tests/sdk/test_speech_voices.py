"""TASK-SSN-B4a contract: voice resolution, output denoise, and content-hash caching.

media.speech gains selectable voices. `_resolve_voice(ctx, voice)` maps a run's `voice` setting to a
reference CLIP path (never None -- so the synth seam always gets an explicit prompt, the isolation
fix from the probe):
  - ""                      -> the bundled default clip (assets/voices/default.wav)
  - "preset:<stem>"         -> assets/voices/<stem>.wav (forced bundled; precedence over owner)
  - "<name-or-id>"          -> a granted owner voice asset via ctx.library.path(...), else a bundled
                               preset of that stem, else the default
  - unsafe id / unknown     -> the default (never a path outside the bundled dir; no traversal)
`_denoise(src, dest)` applies the gentle, deterministic fix the owner chose (highpass ~70 Hz + light
afftdn) to the SYNTH OUTPUT -- reference clips are left raw (cleaning them muffles the clone).
speak() keys its artifact name on the RESOLVED CLIP's content hash (delta A1), so the same voice id
pointing at different clip bytes does not collide in the cache.

Supervisor-authored frozen contract (RED-first); the builder implements sdk/sfvf/media/speech.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import sfvf.media.speech as speech_mod
from sfvf._ffmpeg import _binary, _run, probe
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.grants import GrantStore
from sfvf.library import LibraryStore
from sfvf.media.speech import _denoise, _resolve_voice


def _ctx(tmp: Path, *, workflow_id: str = "wf") -> Context:
    (tmp / "01" / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp / "01" / ".steps").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            workflow_id=workflow_id,
            paths=ContextPaths(
                video=tmp / "01",
                artifacts=tmp / "01" / "artifacts",
                steps=tmp / "01" / ".steps",
                shared=tmp / "01",
                library=tmp / "lib",
                library_owner_pool=tmp / "_owner",
            ),
        )
    )


def _voice_clip(tmp: Path, name: str, *, freq: int = 300) -> Path:
    dest = tmp / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            _binary("ffmpeg"),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration=3",
            "-ac",
            "1",
            "-ar",
            "24000",
            str(dest),
        ]
    )
    return dest


def test_resolve_empty_is_default(tmp_path: Path) -> None:
    clip = _resolve_voice(_ctx(tmp_path), "")
    assert clip.name == "default.wav" and clip.is_file()


def test_resolve_preset_prefix(tmp_path: Path) -> None:
    clip = _resolve_voice(_ctx(tmp_path), "preset:classic-male")
    assert clip.name == "classic-male.wav" and clip.is_file()


def test_resolve_bare_preset_name(tmp_path: Path) -> None:
    clip = _resolve_voice(_ctx(tmp_path), "warm-female")
    assert clip.name == "warm-female.wav" and clip.is_file()


def test_resolve_unknown_preset_falls_back_to_default(tmp_path: Path) -> None:
    clip = _resolve_voice(_ctx(tmp_path), "preset:does-not-exist")
    assert clip.name == "default.wav"


def test_resolve_unsafe_id_falls_back_to_default(tmp_path: Path) -> None:
    for bad in ["../etc/passwd", "preset:../secret", "a/b", "..", "preset:.."]:
        clip = _resolve_voice(_ctx(tmp_path), bad)
        assert clip.name == "default.wav", bad


def test_resolve_never_returns_none_or_missing(tmp_path: Path) -> None:
    # The isolation fix: every resolution yields an existing clip so the synth seam is never
    # called prompt-less.
    for voice in ["", "narrator", "preset:warm-female", "preset:nope", "../x"]:
        clip = _resolve_voice(_ctx(tmp_path), voice)
        assert clip is not None and clip.is_file()


def test_resolve_granted_owner_voice_asset(tmp_path: Path) -> None:
    owner = tmp_path / "_owner"
    src = _voice_clip(tmp_path / "src", "myvoice.wav")
    asset = LibraryStore(owner).put("myvoice.wav", src, kind="voice")
    GrantStore(owner).set_grant(asset.id, {"all": True})
    clip = _resolve_voice(_ctx(tmp_path), asset.id)
    assert clip.read_bytes() == src.read_bytes()  # the granted owner clip, not a preset/default


def test_preset_prefix_beats_owner_asset(tmp_path: Path) -> None:
    # An owner asset aliased "warm-female" must NOT shadow the bundled preset when preset: is used.
    owner = tmp_path / "_owner"
    src = _voice_clip(tmp_path / "src", "wf.wav", freq=500)
    asset = LibraryStore(owner).put("warm-female", src, kind="voice")
    GrantStore(owner).set_grant(asset.id, {"all": True})
    clip = _resolve_voice(_ctx(tmp_path), "preset:warm-female")
    assert clip.name == "warm-female.wav"  # the bundled preset, not the owner asset
    assert clip.read_bytes() != src.read_bytes()


def test_denoise_highpasses_and_preserves_voice_band(tmp_path: Path) -> None:
    # A 40 Hz rumble + a 300 Hz "voice" tone; the gentle fix removes the sub-70 Hz rumble while
    # keeping the 300 Hz band (not muffled).
    noisy = tmp_path / "noisy.wav"
    _run(
        [
            _binary("ffmpeg"),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=40:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:duration=3",
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:normalize=0[a]",
            "-map",
            "[a]",
            "-ac",
            "1",
            "-ar",
            "24000",
            str(noisy),
        ]
    )
    out = tmp_path / "clean.wav"
    _denoise(noisy, out)
    assert out.is_file()
    assert probe(out).duration_s > 0

    def band_db(path: Path, freq: int) -> float:
        stderr = _run(
            [
                _binary("ffmpeg"),
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-af",
                f"bandpass=f={freq}:width_type=h:width=30,volumedetect",
                "-f",
                "null",
                "-",
            ],
            capture_stderr=True,
        )
        m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", stderr)
        assert m
        return float(m.group(1))

    rumble_before, rumble_after = band_db(noisy, 40), band_db(out, 40)
    voice_before, voice_after = band_db(noisy, 300), band_db(out, 300)
    assert rumble_before - rumble_after >= 8.0  # sub-70 Hz rumble strongly cut (~9.8 dB at nf=-30)
    assert voice_before - voice_after <= 4.0  # 300 Hz voice band largely preserved (not muffled)


def test_denoise_uses_the_owner_approved_gentle_filter(tmp_path, monkeypatch) -> None:
    # The exact filter is the owner's A/B-verified "gentle" choice; nf must stay -30 (a higher floor
    # like -25 denoises harder, toward the muffling the owner rejected). Pin it against silent drift
    # -- the band-analysis test above is too loose to catch an nf change.
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return ""

    monkeypatch.setattr(speech_mod, "_run", fake_run)
    _denoise(tmp_path / "in.wav", tmp_path / "out.wav")
    assert calls, "denoise did not invoke ffmpeg"
    cmd = calls[0]
    af = cmd[cmd.index("-af") + 1]
    assert af == "highpass=f=70,afftdn=nr=12:nf=-30"
