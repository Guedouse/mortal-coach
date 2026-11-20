# -*- coding: utf-8 -*-
"""报告地址解析 / 报告结构校验的单测。

跑法（不需要 GUI 依赖，内置解释器即可）：
    runtime\\python\\python.exe tests\\test_urls.py
或
    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "app"))

import main as M  # noqa: E402


def good_report():
    return {
        "player_id": 2,
        "mjai_log": [{"type": "start_kyoku"}, {"type": "tsumo"}],
        "review": {
            "rating": 0.86,
            "total_reviewed": 10,
            "total_matches": 8,
            "model_tag": "4.0",
            "kyokus": [{"entries": [{"tile": "1m"}]}],
        },
    }


class TestResolveDataUrl(unittest.TestCase):
    def test_absolute(self):
        u = M.resolve_data_url(
            "https://mjai.ekyu.moe/killerducky/?data=https%3A%2F%2Fmjai.ekyu.moe%2Freport%2Fa.json")
        self.assertEqual(u, "https://mjai.ekyu.moe/report/a.json")

    def test_root_relative(self):
        u = M.resolve_data_url("https://mjai.ekyu.moe/killerducky/?data=/report/a.json")
        self.assertEqual(u, "https://mjai.ekyu.moe/report/a.json")

    def test_path_relative(self):
        # 相对路径按页面所在目录解析成 /killerducky/report/a.json，另给一个根相对兜底
        cands = M.data_url_candidates("https://mjai.ekyu.moe/killerducky/?data=report/a.json")
        self.assertEqual(cands[0], "https://mjai.ekyu.moe/killerducky/report/a.json")
        self.assertIn("https://mjai.ekyu.moe/report/a.json", cands)

    def test_missing_data(self):
        with self.assertRaises(M.ReportError) as cm:
            M.resolve_data_url("https://mjai.ekyu.moe/killerducky/")
        self.assertEqual(cm.exception.code, "NO_DATA_PARAM")

    def test_blocked_host(self):
        with self.assertRaises(M.ReportError) as cm:
            M.resolve_data_url("https://evil.example.com/killerducky/?data=/report/a.json")
        self.assertEqual(cm.exception.code, "REPORT_URL_INVALID")

    def test_blocked_data_host(self):
        with self.assertRaises(M.ReportError) as cm:
            M.resolve_data_url(
                "https://mjai.ekyu.moe/killerducky/?data=https%3A%2F%2Fevil.example.com%2Fa.json")
        self.assertEqual(cm.exception.code, "DATA_HOST_BLOCKED")

    def test_local_file_blocked(self):
        with self.assertRaises(M.ReportError) as cm:
            M.resolve_data_url("https://mjai.ekyu.moe/killerducky/?data=file:///C:/windows/win.ini")
        self.assertEqual(cm.exception.code, "DATA_HOST_BLOCKED")


class TestValidateReport(unittest.TestCase):
    def test_good(self):
        info = M.validate_report(good_report())
        self.assertEqual(info["events"], 2)
        self.assertEqual(info["seat"], 2)
        self.assertEqual(info["kyokus"], 1)

    def test_missing_mjai_log(self):
        d = good_report()
        d.pop("mjai_log")
        with self.assertRaises(M.ReportError) as cm:
            M.validate_report(d)
        self.assertEqual(cm.exception.code, "REPORT_SCHEMA_INVALID")

    def test_empty_review(self):
        d = good_report()
        d["review"] = {}
        with self.assertRaises(M.ReportError):
            M.validate_report(d)

    def test_empty_kyokus(self):
        d = good_report()
        d["review"]["kyokus"] = []
        with self.assertRaises(M.ReportError):
            M.validate_report(d)

    def test_bad_seat(self):
        d = good_report()
        d["player_id"] = 9
        with self.assertRaises(M.ReportError) as cm:
            M.validate_report(d)
        self.assertEqual(cm.exception.code, "REPORT_SCHEMA_INVALID")

    def test_not_dict(self):
        with self.assertRaises(M.ReportError):
            M.validate_report([1, 2, 3])


class TestTags(unittest.TestCase):
    def test_mortal_paste_normalization(self):
        self.assertEqual(
            M.normalize_pasted_input("牌谱： https://mjai.ekyu.moe/killerducky/?data=/report/a.json。"),
            "https://mjai.ekyu.moe/killerducky/?data=/report/a.json")

    def test_schemeless_url_gets_https(self):
        """从地址栏 / 聊天里复制常丢掉协议头，要能自动补 https。"""
        self.assertEqual(
            M.normalize_pasted_input("game.maj-soul.com/1/?paipu=261118-abc_a116815935"),
            "https://game.maj-soul.com/1/?paipu=261118-abc_a116815935")

    def test_log_id_not_turned_into_url(self):
        """一番街 / 姬麻将的对局 ID 不能被当成网址补协议头。"""
        self.assertEqual(M.normalize_pasted_input("ch35u1e9nc70954ah9n0@3"),
                         "ch35u1e9nc70954ah9n0@3")
        self.assertEqual(M.normalize_pasted_input("2907202_659800c0474bca358929a520"),
                         "2907202_659800c0474bca358929a520")

    def test_mortal_report_input(self):
        self.assertEqual(
            M.report_data_candidates_from_input(
                "https://mjai.ekyu.moe/killerducky/?data=/report/a.json"),
            ["https://mjai.ekyu.moe/report/a.json"])

    def test_tag_from_url(self):
        self.assertEqual(M.tag_from_url("https://game.mahjongsoul.com/?paipu=261118-abcdef"),
                         "261118")

    def test_guess_format(self):
        self.assertEqual(M.guess_format("https://x/y", "auto"), "log-url")
        self.assertEqual(M.guess_format("ch35u1e9nc70954ah9n0@3", "auto"), "riichi-city-log-id")
        self.assertEqual(M.guess_format("2907202_659800c0474bca358929a520", "auto"),
                         "hime-mahjong-log-id")
        self.assertEqual(M.guess_format('{"log":[]}', "auto"), "tenhou6")
        self.assertEqual(M.guess_format("ch35u1e9nc70954ah9n0@3", "auto"),
                         M.guess_format("ch35u1e9nc70954ah9n0@3", "riichi-city-log-id"))

    def test_seat_from_log_id(self):
        self.assertEqual(M.seat_from_log_id("ch35u1e9nc70954ah9n0@3"), "3")
        self.assertEqual(M.seat_from_log_id("ch35u1e9nc70954ah9n0"), "")


class TestNoTokenHint(unittest.TestCase):
    """换机器拿不到 Turnstile token 时，三种原因要给出三种说法（不能笼统说「再点一次」）。"""

    def hint(self, state):
        out = "AT_HOME https://mjai.ekyu.moe/\nNO_TOKEN_STATE " + json.dumps(state) + "\nNO_TOKEN len=0"
        return M.no_token_hint(out, Path("logs/261119.log"))

    def test_page_not_loaded(self):
        msg = self.hint({"form": False, "cf": True, "widget": False})
        self.assertIn("首页没打开", msg)
        self.assertIn("mjai.ekyu.moe", msg)

    def test_cloudflare_script_blocked(self):
        msg = self.hint({"form": True, "cf": False, "widget": True})
        self.assertIn("challenges.cloudflare.com", msg)

    def test_widget_missing(self):
        msg = self.hint({"form": True, "cf": True, "widget": False})
        self.assertIn("没找到人机验证组件", msg)

    def test_manual_challenge(self):
        msg = self.hint({"form": True, "cf": True, "widget": True, "token": 1})
        self.assertIn("显示浏览器窗口", msg)
        self.assertIn("确认您是真人", msg)

    def test_state_missing_still_actionable(self):
        msg = M.no_token_hint("NO_TOKEN len=0", Path("logs/261119.log"))
        self.assertIn("分析", msg)
        self.assertIn("261119.log", msg)

    def test_last_state_wins(self):
        # 先失败在没加载，重试后变成需要人工点：以最后一次状态为准
        out = ('PAGE_STATE {"form": false, "cf": false}\n'
               'NO_TOKEN_STATE {"form": true, "cf": true, "widget": true}\nNO_TOKEN len=0')
        self.assertIn("确认您是真人", M.no_token_hint(out))


class TestNetErrors(unittest.TestCase):
    """报告下载失败不能只甩 WinError 10061，得说清楚是什么毛病。"""

    URL = "https://mjai.ekyu.moe/report/abc?data=/report/abc.json"

    def msg(self, text):
        return M.friendly_net_error(Exception(text), self.URL)

    def test_refused_points_at_proxy(self):
        m = self.msg("[WinError 10061] 由于目标计算机积极拒绝，无法连接。")
        self.assertIn("代理", m)
        self.assertIn(self.URL, m)

    def test_timeout(self):
        self.assertIn("超时", self.msg("timed out"))

    def test_dns(self):
        self.assertIn("解析", self.msg("[Errno 11001] getaddrinfo failed"))

    def test_certificate(self):
        self.assertIn("证书", self.msg("CERTIFICATE_VERIFY_FAILED"))

    def test_unknown_still_has_url(self):
        m = self.msg("weird failure")
        self.assertIn("weird failure", m)
        self.assertIn(self.URL, m)


class TestTileMarks(unittest.TestCase):
    """正文里的牌名占位：后端写 {{2m}}，前端换成牌面图。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(BASE / "scripts"))
        import explain as X
        cls.X = X

    def test_tile_mark(self):
        self.assertEqual(self.X.T("2m"), "{{2m}}")
        self.assertEqual(self.X.T("P"), "{{P}}")
        self.assertEqual(self.X.T("5mr"), "{{5mr}}")

    def test_empty_is_empty(self):
        self.assertEqual(self.X.T(""), "")

    def test_chinese_falls_back_to_text(self):
        # 已经是中文的串不能再套标记，否则前端画不出牌
        self.assertEqual(self.X.T("2万"), "2万")

    def test_strip_restores_names(self):
        self.assertEqual(self.X.strip_tiles("打 {{2m}} 而不是 {{4p}}"), "打 2万 而不是 4筒")
        self.assertEqual(self.X.strip_tiles("打分 12 {{P}}"), "打分 12 白")

    def test_strip_leaves_plain_text(self):
        self.assertEqual(self.X.strip_tiles("没有牌名的一行"), "没有牌名的一行")


class TestBadConfig(unittest.TestCase):
    """恶手分级 / 页面状态都要能落进配置，且旧配置只写一半时不能把默认值冲掉。"""

    def setUp(self):
        self._old = (M.CONFIG_FILE, M.USER_CONFIG)
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.cfg = d / "mortal-coach.json"
        M.CONFIG_FILE = self.cfg
        M.USER_CONFIG = d / "nothing.json"

    def tearDown(self):
        M.CONFIG_FILE, M.USER_CONFIG = self._old
        self._tmp.cleanup()

    def test_defaults(self):
        bad = M.load_config()["bad"]
        self.assertEqual(bad["thresh"], 0.10)
        self.assertEqual(bad["gap"], {"severe": 0.50})
        self.assertEqual(bad["loss"], {"severe": 0.70, "medium": 0.30})
        self.assertNotIn("levels", bad)          # 两档制之后不再有勾选那一层

    def test_partial_file_keeps_defaults(self):
        self.cfg.write_text(json.dumps({"bad": {"gap": {"severe": 0.8}}}), encoding="utf-8")
        bad = M.load_config()["bad"]
        self.assertEqual(bad["gap"]["severe"], 0.8)
        self.assertEqual(bad["thresh"], 0.10)            # 没写的字段保留默认
        self.assertEqual(bad["loss"], {"severe": 0.70, "medium": 0.30})

    def test_legacy_flat_config_migrates(self):
        """旧配置是 {metric, severe, medium}：metric=qloss 时那两个数字属于 Q 刻度。"""
        self.cfg.write_text(json.dumps(
            {"bad": {"metric": "qloss", "severe": 0.9, "medium": 0.2}}), encoding="utf-8")
        bad = M.load_config()["bad"]
        self.assertEqual(bad["loss"], {"severe": 0.9, "medium": 0.2})
        self.assertEqual(bad["thresh"], 0.10)
        # metric=gap 的旧写法的 medium 就是入库门槛
        self.cfg.write_text(json.dumps(
            {"bad": {"metric": "gap", "severe": 0.95, "medium": 0.15}}), encoding="utf-8")
        bad = M.load_config()["bad"]
        self.assertEqual(bad["gap"], {"severe": 0.95})
        self.assertEqual(bad["thresh"], 0.15)

    def test_three_band_config_migrates_to_thresh(self):
        """上一版的三档配置里 gap.medium 就是门槛，迁到 thresh，levels 丢掉。"""
        b = M.norm_bad({"gap": {"severe": 0.55, "medium": 0.12},
                        "loss": {"severe": 0.8, "medium": 0.4},
                        "levels": {"severe": True, "medium": True, "minor": False}})
        self.assertEqual(b["thresh"], 0.12)
        self.assertEqual(b["gap"], {"severe": 0.55})
        self.assertEqual(b["loss"], {"severe": 0.8, "medium": 0.4})
        self.assertNotIn("levels", b)

    def test_two_scales_are_independent(self):
        """门槛、严重线、Q 刻度三者各改各的，互不覆盖。"""
        b = M.norm_bad({"thresh": 0.2, "gap": {"severe": 0.9},
                        "loss": {"severe": 1.1, "medium": 0.5}})
        self.assertEqual(b["thresh"], 0.2)
        self.assertEqual(b["gap"], {"severe": 0.9})
        self.assertEqual(b["loss"], {"severe": 1.1, "medium": 0.5})
        # 严重线写到了门槛之下 → 自动抬到门槛之上（否则「严重」永远为空）
        b2 = M.norm_bad({"thresh": 0.6, "gap": {"severe": 0.2}})
        self.assertGreater(b2["gap"]["severe"], b2["thresh"])
        # Q 刻度倒置 → 中等自动下调
        b3 = M.norm_bad({"loss": {"severe": 0.3, "medium": 0.9}})
        self.assertLess(b3["loss"]["medium"], b3["loss"]["severe"])

    def test_ui_flag_roundtrip(self):
        self.cfg.write_text(json.dumps({"ui": {"welcome_done": True}}), encoding="utf-8")
        self.assertTrue(M.load_config()["ui"]["welcome_done"])

    def test_ui_only_patch_does_not_clear_library(self):
        lib = Path(self._tmp.name) / "lib"
        self.cfg.write_text(json.dumps({"library": str(lib)}), encoding="utf-8")
        old = (M.LIB, M.REPORT, M.COACH, M.IMGS, M.DATA, M.LOGS, M.WORK, M.CONFIG)
        try:
            # 页面只上报「教程已读」，不带 library 字段 —— 库目录必须原样保留
            # （旧实现无条件 cfg["library"] = raw，会把用户设的库目录清空）
            r = M.Api().set_settings({"ui": {"welcome_done": True}})
            self.assertTrue(r.get("ok"), r)
            saved = json.loads(self.cfg.read_text(encoding="utf-8"))
            self.assertEqual(saved.get("library"), str(lib))
            self.assertTrue(saved["ui"]["welcome_done"])
        finally:
            (M.LIB, M.REPORT, M.COACH, M.IMGS, M.DATA, M.LOGS, M.WORK, M.CONFIG) = old

    def test_webview_storage_writable(self):
        p = M.webview_storage()
        self.assertTrue(p and Path(p).is_dir())


class TestEntryThresh(unittest.TestCase):
    """流水线读门槛：环境变量 > 配置文件 > 默认 0.10。"""

    def setUp(self):
        sys.path.insert(0, str(BASE / "scripts"))
        import badcfg
        self.BC = badcfg
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def _write(self, payload):
        (self.dir / "mortal-coach.json").write_text(json.dumps(payload), encoding="utf-8")
        os.environ["MC_APP"] = str(self.dir)

    def test_default_when_nothing_found(self):
        os.environ.pop("MC_BAD_THRESH", None)
        os.environ["MC_APP"] = str(self.dir)          # 目录里没有配置文件
        self.assertAlmostEqual(self.BC.entry_thresh(), 0.10)

    def test_reads_config_thresh(self):
        os.environ.pop("MC_BAD_THRESH", None)
        self._write({"bad": {"thresh": 0.25}})
        self.assertAlmostEqual(self.BC.entry_thresh(), 0.25)

    def test_reads_legacy_gap_medium(self):
        os.environ.pop("MC_BAD_THRESH", None)
        self._write({"bad": {"gap": {"severe": 0.5, "medium": 0.18}}})
        self.assertAlmostEqual(self.BC.entry_thresh(), 0.18)

    def test_env_wins(self):
        self._write({"bad": {"thresh": 0.25}})
        os.environ["MC_BAD_THRESH"] = "0.4"
        self.assertAlmostEqual(self.BC.entry_thresh(), 0.4)

    def test_broken_config_falls_back(self):
        os.environ.pop("MC_BAD_THRESH", None)
        (self.dir / "mortal-coach.json").write_text("{oops", encoding="utf-8")
        os.environ["MC_APP"] = str(self.dir)
        self.assertAlmostEqual(self.BC.entry_thresh(), 0.10)


class TestLibraryPaths(unittest.TestCase):
    """paths.py：界面 / CLI / BAT 共用同一套「牌谱库在哪」的解析。

    这一组就是审计 P1-3 的回归：以前 BAT 只认 <程序目录>/library，
    界面里把库改到别处后，重建写的是另一个库。
    """

    KEYS = ("MC_APP", "MC_LIB")

    def setUp(self):
        sys.path.insert(0, str(BASE / "scripts"))
        import paths
        self.P = paths
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env = {k: os.environ.get(k) for k in self.KEYS}
        os.environ["MC_APP"] = str(self.root)
        os.environ.pop("MC_LIB", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def _cfg(self, payload):
        (self.root / "mortal-coach.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_default_when_nothing_set(self):
        self.assertEqual(self.P.library(), self.root / "library")
        self.assertIn("默认", self.P.library_source())

    def test_reads_config_library(self):
        lib = self.root / "another" / "lib"
        self._cfg({"library": str(lib)})
        self.assertEqual(self.P.library(), lib)
        self.assertIn("配置文件", self.P.library_source())

    def test_cli_beats_config(self):
        self._cfg({"library": str(self.root / "from_config")})
        self.assertEqual(self.P.library(str(self.root / "from_cli")), self.root / "from_cli")
        self.assertIn("--library", self.P.library_source(str(self.root / "from_cli")))

    def test_env_only_when_no_config(self):
        os.environ["MC_LIB"] = str(self.root / "from_env")
        self.assertEqual(self.P.library(), self.root / "from_env")
        self._cfg({"library": str(self.root / "from_config")})   # 有配置就不再理环境变量
        self.assertEqual(self.P.library(), self.root / "from_config")

    def test_relative_library_is_under_app_root(self):
        self._cfg({"library": "library2"})
        self.assertEqual(self.P.library(), self.root / "library2")

    def test_parse_arg_both_forms(self):
        self.assertEqual(self.P.parse_library_arg(["--library", "X"]), "X")
        self.assertEqual(self.P.parse_library_arg(["--library=Y"]), "Y")
        self.assertEqual(self.P.parse_library_arg([]), "")

    def test_apply_sets_env(self):
        self._cfg({"library": str(self.root / "shared")})
        root, lib = self.P.apply()
        self.assertEqual(root, self.root)
        self.assertEqual(lib, Path(os.environ["MC_LIB"]))


class TestPathParity(unittest.TestCase):
    """GUI 与 CLI 必须落在同一个库上（第二次审计 P1-3）。

    以前 GUI 自己展开 `%VAR%`、`~`、相对路径，paths.py 只 `expanduser`，
    配 `%X%/games` 时两边指向不同目录，BAT 会重建错的库。
    """

    def setUp(self):
        sys.path.insert(0, str(BASE / "scripts"))
        import paths
        self.P = paths
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._old_root = M.APP_ROOT
        M.APP_ROOT = self.root
        self._old_env = {k: os.environ.get(k) for k in ("MC_TEST_VAR", "MC_LIB", "MC_BAD_THRESH", "APPDATA", "LOCALAPPDATA")}

    def tearDown(self):
        M.APP_ROOT = self._old_root
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def _both(self, raw):
        """同一个 library 值：GUI 的 resolve_library 与 CLI 的 paths 各算一次。"""
        return (M.resolve_library({"library": raw}), self.P.library_value(raw, self.root))

    def test_env_var_same_on_both_sides(self):
        os.environ["MC_TEST_VAR"] = str(self.root / "mounted")
        gui, cli = self._both("%MC_TEST_VAR%/games")
        self.assertEqual(gui, cli)
        self.assertEqual(gui, self.root / "mounted" / "games")

    def test_home_and_relative_same_on_both_sides(self):
        for raw in ("~/games", "rel/games", "./x/../y"):
            gui, cli = self._both(raw)
            self.assertEqual(gui, cli, raw)
        self.assertEqual(self._both("rel/games")[0], self.root / "rel" / "games")

    def test_empty_means_default_library(self):
        gui, cli = self._both("")
        self.assertEqual(gui, cli)
        self.assertEqual(gui, self.root / "library")

    def test_read_only_app_dir_falls_back_to_instance(self):
        """程序目录不可写：配置与默认库都落到本副本的实例目录，而不是静默丢失。"""
        old = self.P.can_write
        self.P.can_write = lambda d: False
        try:
            cfg = self.P.config_save_path(self.root, local=self.root / "mortal-coach.json",
                                          instance=self.root / "inst" / "config.json")
            self.assertEqual(cfg, self.root / "inst" / "config.json")
            lib = self.P.default_library(self.root)
            self.assertEqual(lib, self.P.instance_dir(self.root) / "library")
        finally:
            self.P.can_write = old

    def test_writable_app_dir_keeps_config_local(self):
        cfg = self.P.config_save_path(self.root, local=self.root / "mortal-coach.json",
                                      instance=self.root / "inst" / "config.json")
        self.assertEqual(cfg, self.root / "mortal-coach.json")


class TestBadcfgSource(unittest.TestCase):
    """门槛只认本副本的配置，不再读 %APPDATA% 的全局旧配置（审计 P1-3）。"""

    def setUp(self):
        sys.path.insert(0, str(BASE / "scripts"))
        import badcfg
        self.B = badcfg
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "app").mkdir()
        self._env = {k: os.environ.get(k) for k in ("MC_APP", "MC_BAD_THRESH", "APPDATA")}
        os.environ.pop("MC_BAD_THRESH", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_ignores_global_appdata_config(self):
        global_cfg = self.root / "global" / "mortal-coach" / "config.json"
        global_cfg.parent.mkdir(parents=True)
        global_cfg.write_text(json.dumps({"bad": {"thresh": 0.5}}), encoding="utf-8")
        os.environ["APPDATA"] = str(self.root / "global")
        app = self.root / "app"
        app.mkdir(exist_ok=True)
        os.environ["MC_APP"] = str(app)
        self.assertEqual(self.B.entry_thresh(), 0.10)      # 全局那份不算数

    def test_reads_local_config(self):
        app = self.root / "app"
        (app / "mortal-coach.json").write_text(json.dumps({"bad": {"thresh": 0.42}}), encoding="utf-8")
        os.environ["MC_APP"] = str(app)
        self.assertEqual(self.B.entry_thresh(), 0.42)

    def test_env_overrides_everything(self):
        app = self.root / "app"
        (app / "mortal-coach.json").write_text(json.dumps({"bad": {"thresh": 0.42}}), encoding="utf-8")
        os.environ["MC_APP"] = str(app)
        os.environ["MC_BAD_THRESH"] = "0.2"
        self.assertEqual(self.B.entry_thresh(), 0.2)


class TestWebView2(unittest.TestCase):
    """界面内核探测（审计 P0-2）：发行包不随包固定版 WebView2，但必须能认出
    系统那份，认不出时要给出可操作的提示，而不是一句看不懂的异常。"""

    def test_system_lookup_returns_pair(self):
        ver, loc = M.webview2_system()
        self.assertIsInstance(ver, str)
        self.assertIsInstance(loc, str)

    def test_version_shape(self):
        ver, _ = M.webview2_system()
        if ver:                                  # 装了才校验形状
            self.assertRegex(ver, r"^\d+\.\d+\.\d+\.\d+$")

    def test_location_exists_when_given(self):
        _, loc = M.webview2_system()
        if loc:
            self.assertTrue((Path(loc) / "msedgewebview2.exe").exists(), loc)

    def test_ready_flag_matches_sources(self):
        self.assertEqual(M.WEBVIEW2_READY,
                         bool(M.WEBVIEW2 or M.WEBVIEW2_VER or M.WEBVIEW2_SYS))

    def test_env_problems_mentions_webview2_only_when_missing(self):
        probs = M.env_problems()
        hit = [p for p in probs if "WebView2" in p]
        self.assertEqual(len(hit), 0 if M.WEBVIEW2_READY else 1)
        if hit:                                  # 缺的时候必须带官方地址
            self.assertIn("developer.microsoft.com", hit[0])

    def test_help_urls_are_https(self):
        self.assertTrue(M.WEBVIEW2_URL.startswith("https://"))
        self.assertTrue(M.WEBVIEW2_PAGE.startswith("https://"))


class _TempRoot(unittest.TestCase):
    """公用：临时程序目录 + 可替换的 paths 模块。"""

    def setUp(self):
        sys.path.insert(0, str(BASE / "scripts"))
        import paths
        self.P = paths
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._old = (M.APP_ROOT, M.CONFIG_FILE, M.USER_CONFIG)
        self._old_cw = self.P.can_write
        self._old_env = {k: os.environ.get(k) for k in
                         ("LOCALAPPDATA", "MC_LIB", "MC_LIB_LOCK_OWNER", "MC_LIB_LOCK_PATH")}

    def tearDown(self):
        M.APP_ROOT, M.CONFIG_FILE, M.USER_CONFIG = self._old
        self.P.can_write = self._old_cw
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def readonly_root(self):
        """模拟「安装目录只读」：目录里还留着出厂默认配置，但写不进去。"""
        self.P.can_write = lambda d: False if Path(d) == self.root else self._old_cw(d)


class TestConfigActivePath(_TempRoot):
    """第三轮审计 P1：只读程序目录里「保存成功、读回旧值」。

    复现的是这条链：出厂默认 0.10 在程序目录 → 保存 0.42 → 确实写进了实例目录 →
    `load_config()` 仍然先读程序目录那份并 break → 界面刷新后设置消失。
    """

    def setUp(self):
        super().setUp()
        self.local = self.root / "mortal-coach.json"
        self.inst = self.root / "inst" / "config.json"
        M.APP_ROOT, M.CONFIG_FILE, M.USER_CONFIG = self.root, self.local, self.inst
        self.local.write_text(json.dumps({"bad": {"thresh": 0.10}, "library": ""}),
                              encoding="utf-8")

    def test_saved_value_is_read_back_on_readonly_dir(self):
        self.readonly_root()
        cfg = M.load_config()
        cfg["bad"]["thresh"] = 0.42
        written = M.save_config(cfg)
        self.assertEqual(written, self.inst)
        self.assertEqual(json.loads(self.inst.read_text(encoding="utf-8"))["bad"]["thresh"], 0.42)
        self.assertEqual(M.load_config()["bad"]["thresh"], 0.42)     # 以前这里是 0.10

    def test_cli_reads_the_same_active_config(self):
        self.readonly_root()
        cfg = M.load_config()
        cfg["bad"]["thresh"] = 0.33
        M.save_config(cfg)
        self.assertEqual(self.P.config_file(self.root, local=self.local, instance=self.inst),
                         self.inst)
        self.assertEqual(self.P.config_read_paths(self.root, local=self.local,
                                                  instance=self.inst)[0], self.inst)

    def test_writable_dir_still_uses_local_config(self):
        cfg = M.load_config()
        cfg["bad"]["thresh"] = 0.21
        self.assertEqual(M.save_config(cfg), self.local)
        self.assertEqual(M.load_config()["bad"]["thresh"], 0.21)

    def test_local_default_only_seeds_when_instance_missing(self):
        """实例配置还不存在时，程序目录那份只当种子，不抢占。"""
        self.readonly_root()
        self.assertEqual(self.P.config_file(self.root, local=self.local, instance=self.inst),
                         self.local)
        self.inst.parent.mkdir(parents=True, exist_ok=True)
        self.inst.write_text(json.dumps({"bad": {"thresh": 0.55}}), encoding="utf-8")
        self.assertEqual(self.P.config_file(self.root, local=self.local, instance=self.inst),
                         self.inst)


class TestLibraryLock(_TempRoot):
    """第三轮审计 P1：锁的三种状态必须分得清，且命令行入口也要过锁闸。"""

    def setUp(self):
        super().setUp()
        self.lib = self.root / "library"
        for d in ("report", "coach", "work", "logs", "img_layout"):
            (self.lib / d).mkdir(parents=True, exist_ok=True)
        (self.lib / "bad_moves.json").write_text("[]", encoding="utf-8")

    def test_free_then_busy_then_free(self):
        st, h = self.P.acquire_lock(self.lib)
        self.assertEqual(st, self.P.LOCK_OK)
        st2, h2 = self.P.acquire_lock(self.lib)
        self.assertEqual(st2, self.P.LOCK_BUSY)
        h.close()
        st3, h3 = self.P.acquire_lock(self.lib)
        self.assertEqual(st3, self.P.LOCK_OK)
        h3.close()

    def test_try_lock_compat_never_reports_success_for_busy(self):
        _, held = self.P.acquire_lock(self.lib)
        self.assertIsNone(self.P.try_lock(self.lib))
        held.close()

    def test_permission_error_is_denied_not_success(self):
        """锁文件建不出来 ≠ 拿到锁。以前这里返回 True，等于无保护放行。"""
        import builtins
        real = builtins.open

        def boom(path, *a, **kw):
            if str(path).endswith(".mc-lock"):
                raise PermissionError("audit")
            return real(path, *a, **kw)

        builtins.open = boom
        try:
            st, h = self.P.acquire_lock(self.lib)
            self.assertEqual(st, self.P.LOCK_DENIED)
            self.assertIsNot(h, True)
            self.assertIs(self.P.try_lock(self.lib), False)
        finally:
            builtins.open = real

    def test_delegated_only_from_direct_parent(self):
        old_ppid, old_alive = self.P.os.getppid, self.P._pid_alive
        self.P.os.getppid = lambda: 4242
        self.P._pid_alive = lambda pid: int(pid) == 4242
        try:
            os.environ["MC_LIB_LOCK_OWNER"] = "4242"
            os.environ["MC_LIB_LOCK_PATH"] = str(self.lib)
            self.assertTrue(self.P.lock_delegated(self.lib))
            os.environ["MC_LIB_LOCK_OWNER"] = "9999"       # 不是父进程：环境变量残留
            self.assertFalse(self.P.lock_delegated(self.lib))
            os.environ["MC_LIB_LOCK_OWNER"] = "4242"
            os.environ["MC_LIB_LOCK_PATH"] = str(self.root / "other")
            self.assertFalse(self.P.lock_delegated(self.lib))
        finally:
            self.P.os.getppid, self.P._pid_alive = old_ppid, old_alive

    def test_guard_writable_refuses_when_another_process_holds_lock(self):
        """真跨进程：本进程持锁，子进程过闸必须退出码 3，且一个文件都不写。"""
        import subprocess
        _, held = self.P.acquire_lock(self.lib)
        try:
            before = sorted(p.name for p in self.lib.iterdir())
            code = ("import sys;sys.path.insert(0,sys.argv[1]);import paths;"
                    "ok,h,m=paths.guard_writable(sys.argv[2],'测试');"
                    "print('OK' if ok else 'REFUSED');"
                    "sys.exit(0 if ok else 3)")
            r = subprocess.run([sys.executable, "-B", "-c", code,
                                str(BASE / "scripts"), str(self.lib)],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
            self.assertIn("REFUSED", r.stdout)
            self.assertEqual(sorted(p.name for p in self.lib.iterdir()), before)
        finally:
            held.close()


class TestGuiMutex(_TempRoot):
    """第四轮审计 P1：删除一局和「保存设置/切库」没有共用互斥，交叉写两个库。

    复现手法与审计一致：把 A 库报告的 unlink 卡住，让删除停在「已持锁、还没写完」，
    此刻另一个线程切到 B 库。修好后设置必须被拒，A 的删除完整作用在 A，B 一个字节不动。
    """

    def setUp(self):
        super().setUp()
        self.app = self.root / "app"
        self.app.mkdir()
        self.lib = self.app / "library"
        self.lib_b = self.root / "library-b"
        self.tag = "990106"
        self.report = {"player_id": 0, "mjai_log": [{"type": "end_game"}],
                       "review": {"rating": 1.0, "total_reviewed": 0,
                                  "total_matches": 0, "kyokus": [{"entries": []}]}}
        for lib, marker in ((self.lib, "A"), (self.lib_b, "B")):
            for d in ("report", "coach", "work", "logs", "img_layout"):
                (lib / d).mkdir(parents=True, exist_ok=True)
            (lib / "coach" / "index.json").write_text("[]", encoding="utf-8")
            (lib / "bad_moves.json").write_text(
                json.dumps([{"game": self.tag, "marker": marker}]), encoding="utf-8")
            (lib / "report" / f"{self.tag}.json").write_text(
                json.dumps(self.report), encoding="utf-8")
        self.cfg = self.app / "mortal-coach.json"
        self.cfg.write_text(json.dumps({"library": str(self.lib)}), encoding="utf-8")

    def _patched(self):
        lib = self.lib
        kw = {"APP_ROOT": self.app, "CONFIG_FILE": self.cfg,
              "USER_CONFIG": self.root / "inst" / "config.json", "LIB": lib, "DATA": lib,
              "REPORT": lib / "report", "COACH": lib / "coach",
              "IMGS": lib / "img_layout", "LOGS": lib / "logs", "WORK": lib / "work",
              "LIB_EXCLUSIVE": True, "LIB_STATE": "ok", "_LIB_LOCK": None,
              "PY": "", "NODE": "", "SCRIPTS": BASE / "scripts"}
        return unittest.mock.patch.multiple(M, **kw)

    def _bad(self, lib):
        return json.loads((lib / "bad_moves.json").read_text(encoding="utf-8"))

    def test_settings_rejected_while_delete_in_flight(self):
        original = Path.unlink
        entered, resume = threading.Event(), threading.Event()
        target = self.lib / "report" / f"{self.tag}.json"

        def gated(p, *a, **kw):
            if p == target:
                entered.set()
                resume.wait(10)
            return original(p, *a, **kw)

        out = {}
        with self._patched():
            self.assertTrue(M.lock_library())
            try:
                api = M.Api()
                t = threading.Thread(target=lambda: out.update(delete=api.delete_game(self.tag)))
                with unittest.mock.patch.object(Path, "unlink", gated):
                    t.start()
                    self.assertTrue(entered.wait(10), "删除没进入持锁阶段")
                    self.assertTrue(api._lock.locked())
                    out["settings"] = api.set_settings({"library": str(self.lib_b)})
                    resume.set()
                    t.join(20)
                    self.assertFalse(t.is_alive())
                # A 的删除完整作用在 A：报告 + 恶手记录都清了
                self.assertFalse(target.exists())
                self.assertEqual(self._bad(self.lib), [])
                # B 一个字节不动：以前这里被切库后的删除尾部清空了
                self.assertTrue((self.lib_b / "report" / f"{self.tag}.json").exists())
                self.assertEqual([r["marker"] for r in self._bad(self.lib_b)], ["B"])
                self.assertFalse(out["settings"]["ok"])
                self.assertIn("正在", out["settings"]["msg"])
                # 收尾后能正常切库（别把设置也一起锁死）
                self.assertTrue(api.set_settings({"library": str(self.lib_b)})["ok"])
                self.assertEqual(Path(M.LIB).resolve(), self.lib_b.resolve())
            finally:
                M.unlock_library()

    def test_two_settings_do_not_interleave(self):
        """一条设置请求在跑，另一条必须被拒，而不是两个都改配置。"""
        with self._patched():
            api = M.Api()
            before = M.CONFIG_FILE.read_text(encoding="utf-8")
            self.assertTrue(api._begin_op("保存设置"))
            try:
                r = api.set_settings({"bad": {"thresh": 0.33}})
                self.assertFalse(r["ok"])
                self.assertTrue(r.get("busy"))
                self.assertEqual(M.CONFIG_FILE.read_text(encoding="utf-8"), before)
            finally:
                api._end_op()
            self.assertTrue(api.set_settings({"bad": {"thresh": 0.33}})["ok"])

    def test_settings_rejected_while_analyzing(self):
        with self._patched():
            api = M.Api()
            self.assertTrue(api._begin_op("分析这一局"))
            try:
                r = api.set_settings({"library": str(self.lib_b)})
                self.assertFalse(r["ok"])
                self.assertIn("分析", r["msg"])
            finally:
                api._end_op()


class TestLayoutCli(_TempRoot):
    """第四轮审计 P2：mk_layout 独立入口读写废弃的 BASE/data/bad_moves.json 且不拿锁。"""

    def _run(self, lib, *extra):
        import subprocess
        env = dict(os.environ)
        for k in ("MC_APP", "MC_LIB", "MC_LIB_LOCK_OWNER", "MC_LIB_LOCK_PATH"):
            env.pop(k, None)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, "-B", str(BASE / "scripts" / "mk_layout.py"),
                               "--library", str(lib), *extra],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120, env=env)

    def test_empty_library_exits_1_without_creating_data_dir(self):
        lib = self.root / "library"
        lib.mkdir()
        r = self._run(lib)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("bad_moves.json", r.stdout + r.stderr)
        self.assertFalse((lib / "img_layout").exists())       # 过闸之前不建目录

    def test_locked_library_exits_3_and_writes_nothing(self):
        lib = self.root / "library"
        lib.mkdir()
        (lib / "bad_moves.json").write_text("[]", encoding="utf-8")
        _, held = self.P.acquire_lock(lib)
        try:
            r = self._run(lib)
            self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
            self.assertFalse((lib / "img_layout").exists())
        finally:
            held.close()

    def test_reads_library_not_app_data(self):
        """源码里不许再出现 BASE/data/bad_moves.json 这种旧路径。"""
        src = (BASE / "scripts" / "mk_layout.py").read_text(encoding="utf-8")
        self.assertNotIn('P / "data"', src)
        self.assertNotIn("BASE / \"data\"", src)


class TestBatLineEndings(unittest.TestCase):
    """第三轮审计 P1：ZIP 里的 BAT 是 LF，cmd 把命令截断成乱码。"""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mc_build", BASE / "build_release.py")
        self.B = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.B)

    def test_normalizes_lf_and_strips_bom(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.bat"
            p.write_bytes(b"\xef\xbb\xbf@echo off\n.\nruntime\\python\\python.exe a.py\n")
            raw = self.B.bat_bytes(p)
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(raw.count(b"\r\n"), 3)
            self.assertEqual(raw.replace(b"\r\n", b"").count(b"\n"), 0)

    def test_repo_bats_are_crlf_without_bom(self):
        for name in ("rebuild.bat", "一键重建解读.bat"):
            raw = (BASE / name).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), name)
            self.assertEqual(raw.replace(b"\r\n", b"").count(b"\n"), 0,
                             f"{name} 有裸 LF，cmd 会截断命令")
            self.assertIn(b"exit /b %RC%", raw, f"{name} 没有把退出码传回去")

    def test_explicit_version_wins(self):
        self.assertEqual(self.B.version("v1.0"), "v1.0")
        self.assertRegex(self.B.version(), r"^\d{8}")


class TestWin10Webview2Acl(unittest.TestCase):
    """第五轮审计 P1：Win10 + 随包 Fixed >= 120 要给目录补 AppContainer 读执行权限。

    官方要求的两条 icacls 只影响 Win10；Win11 不受限，所以本机（Win11）只能靠
    桩把版本号压到 19045 来覆盖逻辑，真实 icacls 往返则在临时目录上实跑。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old_acl = M.WEBVIEW2_ACL, M.WEBVIEW2_ACL_NOTE

    def tearDown(self):
        M.WEBVIEW2_ACL, M.WEBVIEW2_ACL_NOTE = self._old_acl
        self.tmp.cleanup()

    def test_alias_ac_counts_as_all_application_packages(self):
        # SDDL 把 S-1-15-2-1 简写成 AC；只认完整 SID 会把已授权的目录误判成缺权限
        sddl = "D:AI(A;OICI;0x1200a9;;;AC)(A;OICI;0x1200a9;;;S-1-15-2-2)"
        with unittest.mock.patch.object(M, "_dacl_sddl", return_value=sddl):
            self.assertEqual(M._acl_missing_sids(self.dir), [])

    def test_missing_when_aces_absent(self):
        sddl = "D:AI(A;ID;FA;;;BA)(A;ID;FA;;;SY)"
        with unittest.mock.patch.object(M, "_dacl_sddl", return_value=sddl):
            self.assertEqual(M._acl_missing_sids(self.dir),
                             [M.WEBVIEW2_SID_PACKAGES, M.WEBVIEW2_SID_RESTRICTED])

    def test_deny_ace_does_not_count(self):
        sddl = "D:AI(D;OICI;0x1200a9;;;AC)(A;OICI;0x1200a9;;;S-1-15-2-2)"
        with unittest.mock.patch.object(M, "_dacl_sddl", return_value=sddl):
            self.assertIn(M.WEBVIEW2_SID_PACKAGES, M._acl_missing_sids(self.dir))

    def test_win11_needs_nothing(self):
        with unittest.mock.patch.object(M, "windows_build", return_value=26300):
            self.assertEqual(M.webview2_acl_state(self.dir)[0], "not-needed")

    def test_win10_reports_missing(self):
        with unittest.mock.patch.object(M, "windows_build", return_value=19045), \
                unittest.mock.patch.object(M, "_dacl_sddl", return_value="D:AI(A;ID;FA;;;SY)"):
            self.assertEqual(M.webview2_acl_state(self.dir)[0], "missing")

    @unittest.skipUnless(os.name == "nt", "icacls 只在 Windows 上验证")
    def test_grant_roundtrip_on_real_directory(self):
        with unittest.mock.patch.object(M, "windows_build", return_value=19045):
            self.assertEqual(M.webview2_acl_state(self.dir)[0], "missing")
            ok, msg = M.grant_webview2_acl(self.dir)
            self.assertTrue(ok, msg)
            self.assertEqual(M.webview2_acl_state(self.dir)[0], "ok")

    def test_prepare_falls_back_to_system_runtime(self):
        # Win10 上补不了权限、但系统装了 Evergreen → 改用系统那份，不硬闯
        with unittest.mock.patch.object(M, "WEBVIEW2", str(self.dir)), \
                unittest.mock.patch.object(M, "windows_build", return_value=19045), \
                unittest.mock.patch.object(M, "_dacl_sddl", return_value="D:AI(A;ID;FA;;;SY)"), \
                unittest.mock.patch.object(M, "grant_webview2_acl", return_value=(False, "拒绝访问")), \
                unittest.mock.patch.object(M, "WEBVIEW2_VER", "157.0.4341.60"):
            self.assertTrue(M.prepare_webview2(interactive=False))
            self.assertEqual(M.WEBVIEW2_ACL, "system-fallback")
            self.assertEqual(M.WEBVIEW2, "")
            self.assertIn("system runtime", M.WEBVIEW2_ACL_NOTE)

    def test_prepare_fails_when_neither_runtime_usable(self):
        with unittest.mock.patch.object(M, "WEBVIEW2", str(self.dir)), \
                unittest.mock.patch.object(M, "windows_build", return_value=19045), \
                unittest.mock.patch.object(M, "_dacl_sddl", return_value="D:AI(A;ID;FA;;;SY)"), \
                unittest.mock.patch.object(M, "grant_webview2_acl", return_value=(False, "拒绝访问")), \
                unittest.mock.patch.object(M, "WEBVIEW2_VER", ""), \
                unittest.mock.patch.object(M, "WEBVIEW2_SYS", ""):
            self.assertFalse(M.prepare_webview2(interactive=False))
            self.assertEqual(M.WEBVIEW2_ACL, "failed")

    def test_webview2_acl_problem_is_reported(self):
        # 检测到 exe 不等于环境正常：Win10 缺权限时 problems 必须说清楚
        with unittest.mock.patch.object(M, "WEBVIEW2", str(self.dir)), \
                unittest.mock.patch.object(M, "windows_build", return_value=19045), \
                unittest.mock.patch.object(M, "_dacl_sddl", return_value="D:AI(A;ID;FA;;;SY)"):
            probs = M.env_problems()
        self.assertTrue(any("WebView2" in p and "权限" in p for p in probs), probs)

    def test_main_prepares_acl_before_import_webview(self):
        src = (BASE / "app" / "main.py").read_text(encoding="utf-8")
        i_prep = src.index("if not prepare_webview2():")
        i_import = src.index("import webview", i_prep - 1)
        self.assertLess(i_prep, i_import, "权限必须在 import webview / create_window 之前处理好")


class TestFrontendBadMarks(unittest.TestCase):
    """「第一次进牌谱没有恶手标记、重进才有」的回归锁。

    根因是首次进入时 WebView2 网络栈还没就绪，coach 请求失败一次而前端不重试；
    现在要求：请求带重试、NAV 先建好时能补建标记、单条脏数据不毁整批。
    """

    def setUp(self):
        self.src = (BASE / "assets" / "kd" / "index.js").read_text(encoding="utf-8")

    def test_coach_request_retries(self):
        i = self.src.index("async function loadCoach")
        body = self.src[i:i + 1800]
        self.assertRegex(body, r"attempt < \d")
        self.assertIn("setTimeout", body)

    def test_404_does_not_retry(self):
        i = self.src.index("async function loadCoach")
        body = self.src[i:i + 1800]
        self.assertIn("404", body)

    def test_paint_nav_rebuilds_marks_when_missing(self):
        self.assertIn("!Object.keys(NAV_BAD).length && COACH && COACH.moves", self.src)

    def test_single_bad_move_does_not_break_batch(self):
        i = self.src.index("function buildBadMarks")
        body = self.src[i:i + 1200]
        self.assertIn("try {", body)
        self.assertIn("bad move 解析失败", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
