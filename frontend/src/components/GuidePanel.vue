<script setup>
import { useStore } from '../store'
const store = useStore()
</script>

<template>
  <div class="guide">
    <p class="lead">这个工具会盯着你的游戏录像文件夹。每打完一局，它自动找出短时间内的多杀，剪成高光，
      把<b>整局原片 + 高光 + 说明</b>放进同一个文件夹，过几天再自动删掉占空间的整局原片。</p>

    <ol class="steps">
      <li>
        <h3>在 WeGame 里设置录像文件夹</h3>
        <p>用 WeGame「精彩时刻」录制整局，并在它的设置里指定<b>录像导出的文件夹</b>（例如 <code>E:\record</code>）。
          把这个文件夹原样填到本工具的「录像文件夹」里就行，工具会自动找到里面每一局的录像。</p>
      </li>
      <li>
        <h3>（推荐）确认官方标注点</h3>
        <p>游戏录像工具会把每局的击杀、摸金时间记在本机的一个小数据库里。工具读到它就不用逐帧看画面，又快又准。</p>
        <ul>
          <li>默认位置：按 <kbd>Win</kbd>+<kbd>R</kbd>，输入 <code>%APPDATA%\icreate-pc-df\wonderfulDb</code> 回车。
            里面应该有以账号数字命名、没有扩展名的文件。看到了就不用改设置，留空会自动找到。</li>
          <li>需要安装 <a href="https://nodejs.org/zh-cn" target="_blank" rel="noopener">Node.js</a>（选 LTS 版本，一路下一步）才能读取。</li>
          <li>设置 → 识别 里会显示「找到几个账号的标注数据」。显示 ✗ 也能用，只是改为看画面识别，慢一些。</li>
          <li>只读取，不会修改游戏的任何文件。</li>
        </ul>
      </li>
      <li>
        <h3>填写设置</h3>
        <p>点右上角 <b>设置</b>，填三项：<b>游戏 ID</b>（击杀信息里你的名字）、<b>录像文件夹</b>、<b>集锦文件夹</b>（集锦存到哪，例如 <code>D:\集锦</code>，不能放在录像文件夹里）。
          保存后勾上「自动监控新录像」。显卡是 NVIDIA 的话保持「使用 GPU 加速」打开。</p>
      </li>
      <li>
        <h3>打游戏，然后来看</h3>
        <p>一局结束、录像写完后大约 2 分钟开始处理，几分钟后左边列表出现这一局：</p>
        <ul>
          <li><b>大数字</b>是这局的击杀数，橙色表示有集锦。</li>
          <li>点进去可以在「整局原片 / 高光」之间切换播放。</li>
          <li>时间轴上排的菱形是<b>标记</b>（红色击杀、蓝色摸金），只标位置；下排橙色块是<b>片段</b>，整局原片默认带上自动剪的高光。</li>
          <li>把播放头移到想剪的地方，点「在当前位置建片段」；拖片段两端调整范围、拖中间整体移动，选中后可删除。把片段「加入导出」后在右侧导出，文件存回这局的文件夹。</li>
          <li>第一次启用时，录像文件夹里已有的旧录像不会自动处理，在「未处理的旧录像」里点「处理这局」即可。</li>
        </ul>
      </li>
      <li>
        <h3>原片和硬盘空间</h3>
        <p>默认整局原片保留 7 天后自动删除，高光一直保留。想留着某局就点「一直保留原片」；
          也可以随时手动「删除原片」或「删除整个集锦包」。删除前都会确认。</p>
      </li>
    </ol>

    <h3 class="faq-title">常见问题</h3>
    <dl class="faq">
      <dt>识别出的击杀数和结算不一样？</dt>
      <dd>有官方标注点时显示官方结算杀数；集锦只按「不同干员」计算，同一人的击倒和补杀只算一次，摸金和载具不算。</dd>
      <dt>视频黑屏或打不开？</dt>
      <dd>先按 <kbd>Ctrl</kbd>+<kbd>F5</kbd> 刷新；整局原片如果已经到期删除，就只能看高光了。</dd>
      <dt>想剪一段不在录像文件夹里的视频？</dt>
      <dd>点右上角「手动识别」上传，识别完同样可以剪辑导出。</dd>
      <dt>用 4:3 拉伸玩？</dt>
      <dd>设置里保持「集锦拉伸成 16:9」打开，导出的集锦会铺满宽屏。</dd>
    </dl>
    <button class="primary" @click="store.panel = 'settings'">去填设置</button>
  </div>
</template>

<style scoped>
.guide { font-size: 13px; line-height: 1.85; color: var(--text); }
.lead { color: var(--muted); margin-top: 0; }
.steps { padding: 0; margin: 0; list-style: none; counter-reset: step; }
.steps > li { position: relative; padding: 4px 0 14px 40px; counter-increment: step; border-left: 1px solid var(--border); margin-left: 13px; }
.steps > li:last-child { border-left-color: transparent; }
.steps > li::before { content: counter(step); position: absolute; left: -14px; top: 2px; width: 26px; height: 26px; border-radius: 50%; background: var(--accent); color: #1a1205; font: 700 13px/26px Consolas, monospace; text-align: center; }
h3 { margin: 0 0 4px; font-size: 14px; }
p, ul { margin: 4px 0 8px; color: #c4cbd5; } ul { padding-left: 18px; }
code, kbd { font: 12px Consolas, monospace; background: var(--bg); border: 1px solid var(--border); padding: 1px 5px; border-radius: 4px; color: var(--accent-2); }
pre { font: 12px/1.6 Consolas, monospace; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; color: #c4cbd5; overflow-x: auto; }
a { color: var(--accent); }
.faq-title { margin-top: 10px; }
.faq dt { font-weight: 600; margin-top: 10px; } .faq dd { margin: 2px 0 0; color: #c4cbd5; }
.guide > button { margin-top: 18px; width: 100%; }
</style>
