import unittest

from speedylock import bench


class SuggestCapTests(unittest.TestCase):
    def test_picks_largest_standard_step_at_or_below(self):
        self.assertEqual(bench.suggest_cap(143.9), 120)
        self.assertEqual(bench.suggest_cap(144), 144)
        self.assertEqual(bench.suggest_cap(60), 60)
        self.assertEqual(bench.suggest_cap(59.9), 30)
        self.assertEqual(bench.suggest_cap(0), 30)
        self.assertEqual(bench.suggest_cap(1000), 480)

    def test_never_exceeds_measured_floor(self):
        for floor in (45, 61, 89, 118, 200, 350):
            self.assertLessEqual(bench.suggest_cap(floor), floor)


class ParseTests(unittest.TestCase):
    def test_plain_numbers(self):
        text = "\n".join(str(1000.0 / 120) for _ in range(20))
        times = bench.parse_frametimes(text)
        self.assertEqual(len(times), 20)
        self.assertAlmostEqual(times[0], 1000.0 / 120, places=4)

    def test_presentmon_style_csv(self):
        rows = ["Application,ProcessID,FrameTime"]
        rows += ["Deadlock.exe,4242,%s" % v for v in [8.0, 8.5, 9.0] * 5]
        times = bench.parse_frametimes("\n".join(rows))
        self.assertEqual(len(times), 15)
        self.assertAlmostEqual(times[0], 8.0)

    def test_semicolon_delimiter(self):
        rows = ["FrameTime;CPU"]
        rows += ["%s;12.5" % v for v in [7.0] * 12]
        times = bench.parse_frametimes("\n".join(rows))
        self.assertEqual(len(times), 12)

    def test_fps_column_is_converted_to_ms(self):
        rows = ["FPS"] + ["100"] * 12
        times = bench.parse_frametimes("\n".join(rows))
        self.assertAlmostEqual(times[0], 10.0)

    def test_unlabelled_numeric_columns_pick_the_only_numeric_one(self):
        rows = ["nonsense,column"]
        rows += ["x%d,%s" % (i, 6.9) for i in range(12)]
        times = bench.parse_frametimes("\n".join(rows))
        self.assertEqual(len(times), 12)
        self.assertAlmostEqual(times[0], 6.9)

    def test_empty_input_raises(self):
        with self.assertRaises(bench.BenchError):
            bench.parse_frametimes("   ")

    def test_too_few_samples_raise(self):
        with self.assertRaises(bench.BenchError):
            bench.parse_frametimes("16.6\n16.6\n16.6")

    def test_no_numeric_column_raises(self):
        with self.assertRaises(bench.BenchError):
            bench.parse_frametimes("a,b\nc,d\ne,f")

    def test_zero_and_negative_samples_are_dropped(self):
        text = "\n".join(["0", "-5", "10"] + ["10"] * 12)
        times = bench.parse_frametimes(text)
        self.assertTrue(all(t > 0 for t in times))


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        # 99 steady 10ms frames and one 100ms hitch.
        self.times = [10.0] * 99 + [100.0]
        self.stats = bench.analyze(self.times)

    def test_counts_and_mean(self):
        self.assertEqual(self.stats["samples"], 100)
        self.assertAlmostEqual(self.stats["mean_ms"], 10.9, places=4)
        self.assertAlmostEqual(self.stats["mean_fps"], 1000.0 / 10.9, places=3)

    def test_one_percent_low_catches_the_hitch(self):
        self.assertAlmostEqual(self.stats["one_pct_low_fps"], 10.0, places=4)

    def test_one_percent_low_is_not_better_than_median(self):
        self.assertLessEqual(self.stats["one_pct_low_fps"], self.stats["median_fps"])

    def test_stable_cap_is_below_common_cap(self):
        self.assertLessEqual(self.stats["stable_cap"], self.stats["common_cap"])

    def test_steady_capture_is_smooth(self):
        steady = bench.analyze([16.6] * 200)
        self.assertAlmostEqual(steady["stutter_ratio"], 1.0, places=4)
        self.assertLessEqual(steady["stable_cap"], 1000.0 / 16.6)

    def test_empty_raises(self):
        with self.assertRaises(bench.BenchError):
            bench.analyze([])

    def test_report_mentions_both_caps(self):
        report = bench.format_report(self.stats)
        self.assertIn("--fps-cap", report)
        self.assertIn("1% low", report)


class GpuColumnTests(unittest.TestCase):
    """PresentMon renames the GPU-busy column between major versions.

    Every one of these has to work, or a capture from a different PresentMon
    build silently loses the GPU column -- and with it the whole diagnosis.
    """

    @staticmethod
    def build(header, rows):
        return "\n".join([header] + rows)

    def test_1x_msgpuactive(self):
        text = self.build(
            "Application,ProcessID,msBetweenPresents,msGPUActive",
            ["Deadlock.exe,4242,8.0,7.6"] * 12,
        )
        capture = bench.parse_capture(text)
        self.assertEqual(capture.gpu_column, "msgpuactive")
        self.assertFalse(capture.gpu_fallback)

    def test_23_gpubusy(self):
        text = self.build(
            "Application,ProcessID,FrameTime,CPUBusy,GPUBusy",
            ["Deadlock.exe,4242,8.0,2.0,7.6"] * 12,
        )
        capture = bench.parse_capture(text)
        self.assertEqual(capture.gpu_column, "gpubusy")
        self.assertFalse(capture.gpu_fallback)

    def test_24_msgpubusy(self):
        text = self.build(
            "Application,ProcessID,FrameTime,MsCPUBusy,MsGPUBusy",
            ["Deadlock.exe,4242,8.0,2.0,7.6"] * 12,
        )
        capture = bench.parse_capture(text)
        self.assertEqual(capture.gpu_column, "msgpubusy")
        self.assertAlmostEqual(capture.gpu_times[0], 7.6)

    def test_total_gpu_time_is_a_flagged_fallback(self):
        text = self.build(
            "Application,ProcessID,FrameTime,MsGPUTime",
            ["Deadlock.exe,4242,8.0,7.6"] * 12,
        )
        capture = bench.parse_capture(text)
        self.assertEqual(capture.gpu_column, "msgputime")
        self.assertTrue(capture.gpu_fallback)

    def test_busy_column_wins_over_total_time(self):
        text = self.build(
            "Application,ProcessID,FrameTime,MsGPUTime,MsGPUBusy",
            ["Deadlock.exe,4242,8.0,7.9,7.1"] * 12,
        )
        capture = bench.parse_capture(text)
        self.assertEqual(capture.gpu_column, "msgpubusy")
        self.assertAlmostEqual(capture.gpu_times[0], 7.1)

    def test_rows_are_paired_not_filtered_independently(self):
        # A row with no GPU reading must be dropped whole. Filtering each column
        # on its own would pair frame N with frame N+1's GPU time.
        body = ["Deadlock.exe,4242,8.0,7.0", "Deadlock.exe,4242,8.0,"]
        body += ["Deadlock.exe,4242,20.0,19.0"] * 12
        capture = bench.parse_capture(
            self.build("Application,ProcessID,msBetweenPresents,msGPUActive", body)
        )
        self.assertEqual(len(capture.frametimes), len(capture.gpu_times))
        self.assertEqual(len(capture.frametimes), 13)
        self.assertAlmostEqual(capture.frametimes[0], 8.0)
        self.assertAlmostEqual(capture.gpu_times[0], 7.0)

    def test_frame_column_is_never_reused_as_the_gpu_column(self):
        text = "msGPUActive\n" + "\n".join("4.0" for _ in range(20))
        self.assertFalse(bench.parse_capture(text).has_gpu)

    def test_byte_order_mark_and_crlf_are_tolerated(self):
        text = "\ufeff" + self.build(
            "Application,ProcessID,msBetweenPresents,msGPUActive",
            ["Deadlock.exe,4242,8.0,7.6"] * 12,
        ).replace("\n", "\r\n")
        self.assertEqual(len(bench.parse_capture(text).gpu_times), 12)

    def test_absent_gpu_column_is_not_an_error(self):
        text = self.build(
            "Application,ProcessID,msBetweenPresents", ["Deadlock.exe,4242,8.0"] * 12
        )
        capture = bench.parse_capture(text)
        self.assertFalse(capture.has_gpu)
        self.assertIsNone(capture.gpu_column)


if __name__ == "__main__":
    unittest.main()
