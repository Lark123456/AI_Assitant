' Butler WSL 保活：隐藏窗口挂住 Ubuntu distro（WSL 空闲回收根治）
' 由用户启动文件夹自动执行（每次登录），也可手动双击运行
' 注意：用 bash -c 而非 --exec——--exec 的裸进程不被 WSL 计为有效会话，distro 仍会被回收
' 循环重挂：WSL 被意外关闭（wsl --shutdown / 崩溃）时 5 秒后自动拉起，Docker 随 systemd 恢复
Set shell = CreateObject("WScript.Shell")
Do
  shell.Run "C:\Windows\System32\wsl.exe -d Ubuntu -- bash -c ""sleep 86400""", 0, True
  WScript.Sleep 5000
Loop
