"""Tests for capture-driven bottleneck tuning."""

import unittest

from speedylock import bench, tune


def presentmon_csv(frame_ms, gpu_ms, rows=200):
    lines = ["Application,ProcessID,msBetweenPresents,msGPUActive"]
    for _ in range(rows):
        lines.append("Deadlock.exe,4242,%.4f,%.4f" % (frame_ms, gpu_ms))
    return "\n".join(lines)


class CaptureParsingTests(unittest.TestCase):
    def test_reads_both_frame_and_gpu_columns(self):
        capture = bench.parse_capture(presentmon_csv(5.0, 4.8))
        self.assertEqual(len(capture.frametimes), 200)
        self.assertEqual(len(capture.gpu_times), 200)
        self.assertTrue(capture.has_gpu)
        self.assertAlmostEqual(capture.frametimes[0], 5.0)

    def test_works_without_a_gpu_column(self):
        text = "FrameTime\n" + "\n".join("8.0" for _ in range(20))
        capture = bench.parse_capture(text)
        self.assertEqual(len(capture.frametimes), 20)
        self.assertFalse(capture.has_gpu)

    def test_gpu_time_is_not_mistaken_for_frame_time(self):
        # A capture with only a GPU column must not be read as frame intervals.
        text = "msGPUActive\n" + "\n".join("4.0" for _ in range(20))
        capture = bench.parse_capture(text)
        self.assertTrue(all(value == 4.0 for value in capture.frametimes))

    def test_rejects_empty_input(self):
        with self.assertRaises(bench.BenchError):
            bench.parse_capture("   ")


class ClassifyTests(unittest.TestCase):
    def test_gpu_saturated_is_gpu_bound(self):
        capture = bench.parse_capture(presentmon_csv(6.0, 5.9))
        ratio = tune.gpu_ratio(capture)
        self.assertGreater(ratio, 0.93)
        self.assertEqual(tune.classify(ratio), "gpu")

    def test_idle_gpu_is_cpu_bound(self):
        capture = bench.parse_capture(presentmon_csv(8.0, 2.0))
        ratio = tune.gpu_ratio(capture)
        self.assertLess(ratio, 0.75)
        self.assertEqual(tune.classify(ratio), "cpu")

    def test_in_between_is_mixed(self):
        capture = bench.parse_capture(presentmon_csv(8.0, 6.8))
        self.assertEqual(tune.classify(tune.gpu_ratio(capture)), "mixed")

    def test_no_gpu_data_is_unknown(self):
        text = "FrameTime\n" + "\n".join("8.0" for _ in range(20))
        capture = bench.parse_capture(text)
        self.assertIsNone(tune.gpu_ratio(capture))
        self.assertEqual(tune.classify(None), "unknown")


class RenderScaleTests(unittest.TestCase):
    def test_no_scale_when_target_already_met(self):
        self.assertIsNone(tune.suggest_render_scale(200.0, 144.0))

    def test_scale_is_square_root_of_frame_ratio(self):
        # 60fps -> 120fps needs half the pixels, which is a *linear* scale of
        # sqrt(0.5) = 0.71 (not 0.5 -- that is the pixel fraction).
        self.assertAlmostEqual(tune.suggest_render_scale(60.0, 120.0), 0.71, places=2)
        # 100fps -> 144fps: sqrt(100/144) ~= 0.83
        self.assertAlmostEqual(tune.suggest_render_scale(100.0, 144.0), 0.83, places=2)

    def test_scale_squared_is_the_pixel_fraction(self):
        scale = tune.suggest_render_scale(60.0, 120.0)
        self.assertAlmostEqual(scale * scale, 0.5, places=1)

    def test_trivial_changes_are_not_worth_recommending(self):
        # 161 -> 165fps would be a 0.99 scale: acknowledged as not worth it.
        self.assertIsNone(tune.suggest_render_scale(161.0, 165.0))

    def test_scale_is_clamped_to_a_readable_floor(self):
        self.assertEqual(tune.suggest_render_scale(20.0, 1000.0), 0.5)
        self.assertEqual(tune.suggest_render_scale(1000.0, 1.0), None)

    def test_degenerate_inputs_return_none(self):
        self.assertIsNone(tune.suggest_render_scale(0, 144))
        self.assertIsNone(tune.suggest_render_scale(None, 144))
        self.assertIsNone(tune.suggest_render_scale(144, 0))


class CapOptionTests(unittest.TestCase):
    def setUp(self):
        self.stats = {
            "stable_cap": 120,
            "common_cap": 180,
            "mean_fps": 210.0,
        }

    def test_stable_is_the_one_percent_low_cap(self):
        self.assertEqual(tune.cap_options(self.stats)["stable"], 120)

    def test_vrr_cap_never_exceeds_stable(self):
        options = tune.cap_options(self.stats, refresh=240)
        self.assertEqual(options["vrr"], 120)

    def test_vrr_cap_sits_under_refresh_when_that_is_lower(self):
        options = tune.cap_options(self.stats, refresh=100)
        self.assertEqual(options["vrr"], 97)

    def test_tick_cap_aligns_to_60hz(self):
        self.assertEqual(tune.cap_options(self.stats)["tick"], 120)
        stats = dict(self.stats, stable_cap=90)
        self.assertEqual(tune.cap_options(stats)["tick"], 60)

    def test_recommendation_prefers_vrr_and_sizes_render_scale(self):
        capture = bench.parse_capture(presentmon_csv(9.0, 8.9))
        stats = {"stable_cap": 120, "common_cap": 180, "mean_fps": 111.0}
        result = tune.recommendation(stats, capture, refresh=144)
        self.assertEqual(result["verdict"], "gpu")
        self.assertEqual(result["cap"], 120)  # min(stable 120, refresh-3 141)
        self.assertIsNotNone(result["render_scale"])

    def test_cpu_bound_gives_no_render_scale(self):
        capture = bench.parse_capture(presentmon_csv(9.0, 2.0))
        stats = {"stable_cap": 120, "common_cap": 180, "mean_fps": 111.0}
        result = tune.recommendation(stats, capture, refresh=144)
        self.assertEqual(result["verdict"], "cpu")
        self.assertIsNone(result["render_scale"])


class AdviceTests(unittest.TestCase):
    def _result(self, verdict, scale=None, vrr=None):
        return {
            "verdict": verdict,
            "ratio": 0.95 if verdict == "gpu" else 0.5,
            "caps": {"stable": 120, "fast": 180, "tick": 120, "vrr": vrr, "refresh": 144},
            "cap": vrr or 120,
            "render_scale": scale,
        }

    def test_cpu_advice_tells_you_not_to_lower_resolution(self):
        text = " ".join(tune.advice(self._result("cpu")))
        self.assertIn("buys you nothing", text)
        self.assertIn("potato", text)

    def test_gpu_advice_mentions_the_render_scale(self):
        text = " ".join(tune.advice(self._result("gpu", scale=0.79)))
        self.assertIn("0.79", text)

    def test_unknown_verdict_asks_for_gpu_timings(self):
        text = " ".join(tune.advice(self._result("unknown")))
        self.assertIn("msGPUActive", text)

    def test_install_command_includes_scale_only_for_gpu(self):
        gpu = tune.install_command(self._result("gpu", scale=0.8), "balanced")
        self.assertIn("--render-scale 0.80", gpu)
        self.assertIn("--fps-cap 120", gpu)
        cpu = tune.install_command(self._result("cpu"), "potato")
        self.assertNotIn("--render-scale", cpu)


class GpuMeasurementGuardTests(unittest.TestCase):
    """An unusable GPU column must read as unknown, never as a wrong verdict."""

    def test_all_zero_gpu_column_is_not_reported_as_cpu_bound(self):
        # PresentMon still writes the column when the driver cannot measure it.
        capture = bench.parse_capture(presentmon_csv(8.0, 0.0))
        self.assertIsNone(tune.gpu_ratio(capture))
        self.assertEqual(tune.classify(None), "unknown")

    def test_impossible_ratio_is_rejected(self):
        capture = bench.parse_capture(presentmon_csv(8.0, 20.0))
        self.assertIsNone(tune.gpu_ratio(capture))

    def test_presentmon_2_header_is_understood_end_to_end(self):
        lines = ["Application,ProcessID,FrameTime,MsGPUBusy"]
        lines += ["Deadlock.exe,4242,8.0,7.6"] * 50
        capture = bench.parse_capture("\n".join(lines))
        self.assertEqual(tune.classify(tune.gpu_ratio(capture)), "gpu")


if __name__ == "__main__":
    unittest.main()
