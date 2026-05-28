# Vendor Config

このフォルダは、配布したいMOD設定ファイルを入れる場所です。

ここに置いたファイルやサブフォルダは、ランチャーの `config適用` または `MOD自動DL` 実行時に、専用ゲームフォルダの `config` へ同じ階層でコピーされます。

例:

- `vendor/config/enderio/enderio.cfg` -> `<instance>/config/enderio/enderio.cfg`
- `vendor/config/cofh/world/00_minecraft.json` -> `<instance>/config/cofh/world/00_minecraft.json`

既存のconfigは通常上書きしません。更新版を強制適用したい場合は、GUIの `config適用` で上書きを選ぶか、CLIで `--install-configs --overwrite-configs` を使ってください。

現在含めているconfig:

- `net.minecraft.scalar.mineall.mod_mineallsmp.cfg`: 安山岩/花崗岩/閃緑岩をMineAll対象から外し、自動回収を有効にし、導入MODの鉱石を追加します。
- `cofh/world/01_thermalfoundation_ores.json`: Thermal Foundationのアルミニウム鉱石生成を有効にします。

この `README.md` はコピー対象外です。
