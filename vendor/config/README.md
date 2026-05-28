# Vendor Config

このフォルダは、配布したいMOD設定ファイルを入れる場所です。

ここに置いたファイルやサブフォルダは、ランチャーの `config適用` または `MOD自動DL` 実行時に、専用ゲームフォルダの `config` へ同じ階層でコピーされます。

例:

- `vendor/config/enderio/enderio.cfg` -> `<instance>/config/enderio/enderio.cfg`
- `vendor/config/cofh/world/00_minecraft.json` -> `<instance>/config/cofh/world/00_minecraft.json`

既存のconfigは通常上書きしません。更新版を強制適用したい場合は、GUIの `config適用` で上書きを選ぶか、CLIで `--install-configs --overwrite-configs` を使ってください。

この `README.md` はコピー対象外です。
