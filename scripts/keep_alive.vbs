' Butler WSL 保活：隐藏窗口挂住 Ubuntu distro（WSL 空闲回收根治）
' 由用户启动文件夹自动执行（每次登录），也可手动双击运行
' 注意：用 bash -c 而非 --exec——--exec 的裸进程不被 WSL 计为有效会话，distro 仍会被回收
CreateObject("WScript.Shell").Run "wsl.exe -d Ubuntu -- bash -c ""sleep infinity""", 0, False
