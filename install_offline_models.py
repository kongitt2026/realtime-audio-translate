# 安装 Argos 离线翻译模型：日→中、韩→中
# Argos 官方索引没有 ja→zh / ko→zh 直连包，装 ja→en、ko→en 后由库内自动经英文中转
# （argostranslate.translate.get_installed_languages 里有 CompositeTranslation 拼接逻辑）
# 用法：
#   .venv\Scripts\python.exe install_offline_models.py           安装缺失模型并验证
#   .venv\Scripts\python.exe install_offline_models.py --check   只看现状，不下载
# 费用：0 元；下载源 argos-net.com 官方免费；ja_en 约 112MB、ko_en 约 113MB、en_zh 约 100MB
import sys
import time

import argostranslate.package as ap
import argostranslate.translate as at

# 离线 ja/ko→zh 所需的最小包集合
REQUIRED = [("ja", "en"), ("ko", "en"), ("en", "zh")]
SAMPLES = {
    "ja": "今日はとても良い天気です。これから公園へ行きます。",
    "ko": "오늘은 날씨가 정말 좋습니다. 우리는 공원에 갈 거예요.",
}


def main() -> int:
    check_only = "--check" in sys.argv[1:]

    print("[1] 更新 Argos 官方模型索引…")
    ap.update_package_index()
    available = {(p.from_code, p.to_code): p for p in ap.get_available_packages()}
    installed = {(p.from_code, p.to_code) for p in ap.get_installed_packages()}

    todo = []
    for pair in REQUIRED:
        if pair in installed:
            state = "已安装"
        elif pair in available:
            state = "待安装"
            todo.append(pair)
        else:
            state = "索引中不存在"
        print(f"    {pair[0]} → {pair[1]}：{state}")

    if check_only:
        print("[2] --check 模式，跳过下载")
    else:
        for from_code, to_code in todo:
            pkg = available[(from_code, to_code)]
            print(f"[2] 下载并安装 {from_code} → {to_code}（v{pkg.package_version}）…")
            t0 = time.time()
            pkg.install()  # 下载到 downloads 目录后解压安装，安装完自动删除原包
            print(f"    完成，用时 {time.time() - t0:.0f}s")

    # 清 lru_cache，让新装包在当前进程立即生效（服务进程内装包才需要；重启服务同样生效）
    at.get_installed_languages.cache_clear()

    langs = {lang.code: lang for lang in at.get_installed_languages()}
    zh = langs.get("zh")
    ok = True
    for code, text in SAMPLES.items():
        if zh is None or code not in langs or langs[code].get_translation(zh) is None:
            print(f"[3] {code} → zh：不可用（缺 {code}→en 或 en→zh）")
            ok = False
            continue
        print(f"[3] {code} → zh：{at.translate(text, code, 'zh')}")

    print("[4] 结论：" + ("离线日/韩→中可用（经英文中转）" if ok else "仍有模型缺失，兜底不可用"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
