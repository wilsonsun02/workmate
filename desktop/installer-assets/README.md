# installer-assets

将离线 Node 安装包放在本目录，文件名需与 `installer.iss` 一致：

- `node-v20.19.0-x64.msi`

建议来源：Node.js 官方 MSI 安装包（Windows x64）。

编译 `desktop/installer.iss` 前请先确认该文件存在，否则 Inno Setup 会报 `Source file not found`。
