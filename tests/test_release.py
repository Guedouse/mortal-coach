"""打包口径的回归测试：lite / full 两种资产不能互相夹带。

只测 `build_release.iter_release_files` 的白名单逻辑，不真的打 600 MB 的包：
造一个假的程序目录，看两种 flavor 各自枚举出哪些 ZIP 内路径。

为什么值得单独测：开发机上为了打 full 包，`runtime/chromium` 与 `runtime/webview2`
是真实存在的（1.5 GB 上下）。少一个排除条件，lite 包就会悄悄从 76 MB 变成 600 MB，
而这种"错"在验包里不一定报错 —— 只是有人下载完才发现。
"""

import importlib.util
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

_spec = importlib.util.spec_from_file_location("build_release", ROOT / "build_release.py")
BR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BR)


class TestFlavorFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mc_release_"))
        # 最小可用的假程序目录：只是想看白名单怎么走，内容无所谓
        for rel in ("runtime/python/python.exe",
                    "runtime/node/node.exe",
                    "runtime/chromium/chrome.exe",
                    "runtime/webview2/152.0.4191.53/msedgewebview2.exe",
                    "runtime/webview2/152.0.4191.53/msedge.dll"):
            p = self.tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
        (self.tmp / "notes.txt").write_text("x", encoding="utf-8")
        self._old = (BR.BASE, list(BR.REQUIRED_FILES), list(BR.INCLUDE_DIRS))
        BR.BASE = self.tmp
        BR.REQUIRED_FILES = ["notes.txt"]
        BR.INCLUDE_DIRS = ["runtime"]

    def tearDown(self):
        BR.BASE, BR.REQUIRED_FILES, BR.INCLUDE_DIRS = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def arcs(self, flavor):
        return [arc for _, arc in BR.iter_release_files(flavor)]

    def test_lite_excludes_bundled_engines(self):
        arcs = self.arcs("lite")
        self.assertIn("runtime/python/python.exe", arcs)
        self.assertIn("runtime/node/node.exe", arcs)
        self.assertFalse([a for a in arcs if a.startswith("runtime/chromium/")])
        self.assertFalse([a for a in arcs if a.startswith("runtime/webview2/")])

    def test_full_includes_only_interface_runtime(self):
        arcs = self.arcs("full")
        self.assertFalse([a for a in arcs if a.startswith("runtime/chromium/")])
        self.assertIn("runtime/webview2/152.0.4191.53/msedgewebview2.exe", arcs)
        self.assertIn("runtime/webview2/152.0.4191.53/msedge.dll", arcs)
        self.assertIn("runtime/python/python.exe", arcs)

    def test_both_flavors_are_offered(self):
        self.assertEqual(sorted(BR.FLAVORS), ["full", "lite"])

    def test_find_webview2_dir_picks_version_folder(self):
        # 官方固定版解压后是「版本号」这一层目录，程序与打包脚本都要认得出
        found = BR.find_webview2_dir()
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "152.0.4191.53")

    def test_lite_manifest_does_not_claim_bundled_engines(self):
        """开发目录里有 1.5 GB 内核，但 lite 包不带 —— 清单不能谎称 bundled。"""
        rv = BR.runtime_versions("lite")
        self.assertIn("system", rv["webview2"])
        self.assertIn("system", rv["chromium"])
        rv_full = BR.runtime_versions("full")
        self.assertIn("bundled", rv_full["webview2"])
        self.assertIn("system", rv_full["chromium"])


class TestLeakPatterns(unittest.TestCase):
    """发行包里不许出现作者本机路径，但系统路径（Program Files / Windows）是正常的。

    中文用户的库目录常常长成「盘符 + 中文」，旧的开发目录与用户目录规则完全拦不住，
    所以这里把两类都钉住：个人目录 + 非 ASCII 目录名。
    """

    @staticmethod
    def hits(text):
        return [why for rx, why in BR.LEAK_RES if rx.search(text)]

    def test_personal_paths_flagged(self):
        bs = chr(92)
        for p in (f"D:{bs}maa", f"C:/Users/" + "SampleUser", f"C:{bs}Users{bs}Somebody{bs}Desktop",
                  f"D:{bs}麻将复盘{bs}牌谱库"):
            self.assertTrue(self.hits(p), p)

    def test_system_paths_and_urls_allowed(self):
        for p in ("C:/Program Files/Google/Chrome/Application/chrome.exe",
                  "C:/Windows/Fonts/msyh.ttc",
                  "https://game.maj-soul.com/1/?paipu=xxx",
                  "https://…、根相对 /report/xxx.json",
                  "D:/mahjong-lib"):
            self.assertEqual(self.hits(p), [], p)


class TestBuildSource(unittest.TestCase):
    def test_runtime_pip_is_not_a_release_dependency(self):
        self.assertTrue(BR.in_skip_dir('runtime/python/Lib/site-packages/pip'))
        self.assertTrue(BR.in_skip_dir('runtime/python/Lib/site-packages/pip-26.1.2.dist-info'))
        self.assertFalse(BR.in_skip_dir('runtime/python/Lib/site-packages/PIL'))

    def test_failed_git_command_does_not_become_head_commit(self):
        with patch.object(BR, 'sh', return_value='HEAD'):
            self.assertEqual(BR.source_info(), {'commit': None, 'dirty': None})

    def test_clean_git_source_revision_is_recorded(self):
        commit = '0123456789abcdef' * 2 + '01234567'
        with patch.object(BR, 'sh', side_effect=[commit, '']):
            self.assertEqual(BR.source_info(), {'commit': commit, 'dirty': False})


if __name__ == "__main__":
    unittest.main(verbosity=2)
