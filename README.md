# MC 1.12.2 Forge MOD Launcher

Minecraft 1.12.2 + Forge `14.23.5.2859` 用の自作ランチャー補助ツールです。

このツールが行うこと:

- Forge 1.12.2 のクライアント導入
- 専用ゲームフォルダ `~/MinecraftInstances/MC1122-JP-Modpack` または `%USERPROFILE%\MinecraftInstances\MC1122-JP-Modpack` の作成
- Modrinth APIで取れるMODの自動ダウンロード
- CurseForge CDNから取れるMODの自動ダウンロード
- `vendor/mods` に置いた手動取得MODの自動取り込み
- `vendor/config` に置いたMOD設定ファイルの自動適用
- CurseForge等から落としたMOD jar/zip/litemodの手動取り込み
- Forge server用フォルダの出力
- 公式Minecraft Launcher用プロファイルの作成
- 公式Minecraft Launcherの起動

## 使い方

GUIで起動:

Windows:

```bat
run.bat
```

macOS/Linux:

```bash
./run.sh
```

CLIでまとめて実行:

Windows:

```bat
run.bat --check --install-forge --download-mods --create-profile
```

macOS/Linux:

```bash
./run.sh --check --install-forge --download-mods --create-profile
```

公式ランチャーを起動:

Windows:

```bat
run.bat --launch
```

macOS/Linux:

```bash
./run.sh --launch
```

サーバー用フォルダを作る:

Windows:

```bat
run.bat --download-mods --export-server
```

macOS/Linux:

```bash
./run.sh --download-mods --export-server
```

Forge版を変えたい場合は環境変数で上書きできます。

Windows:

```bat
set MC1122_FORGE_VERSION=14.23.5.2864
run.bat --install-forge --create-profile
```

macOS/Linux:

```bash
MC1122_FORGE_VERSION=14.23.5.2864 ./run.sh --install-forge --create-profile
```

このマニフェストに入っているCurseForge MODは、固定した `file id` からCDN URLを生成するため、通常はCurseForge APIキーなしで取得できます。
固定情報がないMODを追加した場合は、CurseForge APIキーを指定すると取得が安定します。

```bash
CURSEFORGE_API_KEY=あなたのAPIキー ./run.sh --download-mods
```

Windowsのコマンドプロンプトでは次の形です。

```bat
set CURSEFORGE_API_KEY=あなたのAPIキー
run.bat --download-mods
```

CLI引数でも指定できます。

Windows:

```bat
run.bat --curseforge-api-key あなたのAPIキー --download-mods
```

macOS/Linux:

```bash
./run.sh --curseforge-api-key あなたのAPIキー --download-mods
```

APIキーがない未固定MODは、公開索引/配布URL推定で取得を試しますが、CurseForge側の仕様変更で失敗する場合があります。

## 友人に配る時

配布するのはランチャー本体とマニフェストだけで十分です。MOD jar本体は各自のPCで配布元から自動取得します。

入れるもの:

- `launcher.py`
- `mods_manifest.json`
- `run.bat`
- `run.sh`
- `README.md`
- `THIRD_PARTY_NOTICES.md`
- `vendor/mods/README.md`
- `vendor/config/README.md`
- `vendor/config` 配下の配布したいMOD設定ファイル

入れないもの:

- `launcher_settings*.json`
- `.git` / `.codex` / `.agents`
- `__pycache__`
- `MinecraftInstances` や `.minecraft`
- ダウンロード済みのMOD jar/litemod/zip本体

サーバー用フォルダはMOD jar本体を含むため、ランチャー配布ZIPには入れないでください。サーバー管理者のPCで `server出力` または `--export-server` を実行して生成します。

## MOD configを配る

配布したいMOD設定ファイルは、ランチャー側の `vendor/config` にゲーム内 `config` と同じ階層で置きます。

例:

- `vendor/config/enderio/enderio.cfg` -> `<instance>/config/enderio/enderio.cfg`
- `vendor/config/cofh/world/00_minecraft.json` -> `<instance>/config/cofh/world/00_minecraft.json`

GUIでは「MOD自動DL」実行時に未導入のconfigをコピーします。configだけ適用したい場合は「config適用」を押してください。既存configは通常上書きしません。上書きしたい場合は「config適用」で確認に「はい」を選びます。

現在はMineAll用configとCoFH World用のThermal Foundation鉱石生成configを同梱しています。MineAllは安山岩/花崗岩/閃緑岩を一括破壊対象から外し、破壊アイテムの自動回収を有効化し、IC2/Mekanism/Thermal Foundation/Applied Energistics 2/Tinkers' Constructの鉱石を対象に追加しています。Thermal Foundationの鉱石生成ではアルミニウム鉱石を有効化しています。

CLIでは `--download-mods` 実行時に未導入のconfigもコピーします。configだけ適用する場合は次のように実行します。

```bat
run.bat --install-configs
```

既存configも上書きして更新する場合:

```bat
run.bat --install-configs --overwrite-configs
```

## サーバー用フォルダ

GUIでは「server出力」を押すと、`MC1122-JP-Modpack-Server` フォルダを作ります。CLIでは `--export-server` を使います。

出力内容:

- Forge server jarとライブラリ
- server用MODだけを入れた `mods`
- `config` のコピー
- `start_server.bat`
- `start_server.sh`
- `server.properties`
- `eula.txt`

`Gammabright`、`ToroHealth Damage Indicators`、`VoxelMap` はクライアント専用としてサーバーから除外します。`Just Enough Items (JEI)` はレシピ転送/整列機能の互換性のためサーバーにも入れます。

初回起動前に `eula.txt` を開き、MojangのEULAに同意する場合だけ `eula=true` に変更してください。

## 手順

1. Minecraft: Java Edition の公式ランチャーを一度起動し、ログインしておきます。
2. このツールで「環境チェック」を押します。
3. 「Forge導入」を押します。
4. 「MOD自動DL」を押します。
5. ログに出た「手動導入が必要なMOD」だけ各配布ページからダウンロードします。
6. 「手動MOD追加」でダウンロードした `.jar` / `.zip` / `.litemod` を取り込みます。
7. 「プロファイル作成」を押します。
8. 「公式ランチャー起動」を押し、`MC 1.12.2 JP Modpack` を選んで起動します。

## 軽量化MOD

OptiFineは収録対象から外し、軽量化MODとして `VintageFix` を追加しています。`VintageFix` は1.12.2向けのロード時間/RAM使用量改善MODで、必須依存の `MixinBooter` も自動取得対象です。

`Gammabright` はCurseForgeから取得対象にしていますが、配布ページ上ではLiteLoader必須です。Forgeだけで読み込めない場合は、Minecraftの `options.txt` の `gamma` 設定で代替してください。

## 注意

- MOD本体を追加する場合は、各MODの配布元とライセンスに従ってください。
- Windowsでは `run.bat` を使ってください。Python Launcherが入っていれば `py -3`、なければ `python` で起動します。
- Minecraft 1.12.2はJava 8が最も安定します。公式ランチャーの同梱Javaで動く場合もあります。
- Javaの場所にスペースがある場合は、GUIのJava欄の「選択」から `java.exe` を指定してください。
- 設定ファイルはOS別に `launcher_settings.windows.json` / `launcher_settings.linux.json` のように保存します。
- listed MOD同士の相性までは保証できません。初回起動でクラッシュした場合は `mods` フォルダから1つずつ外して原因を切り分けてください。
- Storage Drawers/Chameleonのように配布元違いでクラッシュする組み合わせは、既存jarを削除せず `.disabled` に退避してから固定版を入れます。
- 既存の `launcher_profiles.json` は書き換え前にバックアップを作ります。
- `VintageFix` はOptiFineやFoamFixと併用しないでください。

## 収録対象

ユーザー指定MOD:

- IndustrialCraft 2
- BuildCraft
- Ender IO
- Mekanism
- Mekanism Generators
- Thermal Expansion
- Industrial Foregoing
- Applied Energistics 2
- Tinkers' Construct
- Extra Utilities 2
- CutAll
- MineAll
- Gammabright
- Bloodmoon
- VintageFix
- Iron Chests
- Just Enough Items (JEI)
- ToroHealth Damage Indicators
- VoxelMap
- OpenBlocks
- Storage Drawers
- The Twilight Forest
- GVCReversion2

必要になりやすい依存MOD:

- EnderCore
- CoFH Core
- Redstone Flux
- CoFH World
- Thermal Foundation
- Tesla Core Lib
- Forgelin
- CodeChickenLib
- Mantle
- OpenModsLib
- Chameleon
- MixinBooter
- GVCLib
