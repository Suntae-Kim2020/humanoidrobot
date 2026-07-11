#!/usr/bin/env python3
"""Encrypt a static HTML page with a password (AES-256-GCM + PBKDF2-SHA256).
Output = a black-themed password gate that decrypts in-browser (Web Crypto).
Usage: python encrypt_page.py <input.html> <output.html> [password]"""
import sys, base64, secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 250000

def encrypt(plaintext, password):
    salt = secrets.token_bytes(16); iv = secrets.token_bytes(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, plaintext, None)
    b = lambda x: base64.b64encode(x).decode()
    return b(salt), b(iv), b(ct)

GATE = r'''<title>&#128274; 암호 필요</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 html,body{margin:0;height:100%;background:#000;color:#fff;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
 .gate{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
 .box{width:100%;max-width:380px;text-align:center}
 .lk{font-size:40px}
 h1{font-size:19px;font-weight:700;margin:14px 0 4px}
 p{font-size:13.5px;color:#c3c2b7;line-height:1.6;margin:0 0 20px}
 form{display:flex;gap:8px}
 input{flex:1;background:#141413;border:1px solid rgba(255,255,255,.16);border-radius:10px;color:#fff;font-size:15px;padding:11px 13px;outline:none}
 input:focus{border-color:#3987e5}
 button{background:#3987e5;color:#fff;border:0;border-radius:10px;font-size:14px;font-weight:600;padding:0 18px;cursor:pointer}
 button:disabled{opacity:.6}
 .msg{min-height:18px;font-size:12.5px;color:#e66767;margin-top:12px}
 .hint{font-size:11.5px;color:#8f8d86;margin-top:22px;line-height:1.5}
</style>
<div class="gate"><div class="box">
 <div class="lk">&#128274;</div>
 <h1>암호로 보호된 페이지</h1>
 <p>중국 휴머노이드 로봇 동향 대시보드입니다.<br>접근 암호를 입력하세요.</p>
 <form id="f"><input id="pw" type="password" placeholder="암호" autofocus autocomplete="current-password"><button id="b" type="submit">열기</button></form>
 <div class="msg" id="m"></div>
 <div class="hint">이 페이지는 AES-256으로 암호화되어 있으며, 올바른 암호 없이는 내용을 볼 수 없습니다.</div>
</div></div>
<script>
const SALT="__SALT__",IV="__IV__",CT="__CT__",ITER=__ITER__;
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function tryDecrypt(pw){
 const enc=new TextEncoder();
 const km=await crypto.subtle.importKey("raw",enc.encode(pw),"PBKDF2",false,["deriveKey"]);
 const key=await crypto.subtle.deriveKey({name:"PBKDF2",salt:b64(SALT),iterations:ITER,hash:"SHA-256"},km,{name:"AES-GCM",length:256},false,["decrypt"]);
 const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:b64(IV)},key,b64(CT));
 return new TextDecoder().decode(pt);
}
function render(html){ sessionStorage.setItem("hr_pw","1"); document.open(); document.write(html); document.close(); }
async function go(pw,silent){
 const b=document.getElementById("b"),m=document.getElementById("m");
 if(b){b.disabled=true;} if(m){m.textContent="";}
 try{ const html=await tryDecrypt(pw); render(html); }
 catch(e){ if(!silent&&m)m.textContent="암호가 올바르지 않습니다."; if(b)b.disabled=false; }
}
document.getElementById("f").addEventListener("submit",e=>{e.preventDefault();go(document.getElementById("pw").value,false);});
</script>'''

def main():
    inp, outp = sys.argv[1], sys.argv[2]
    pw = sys.argv[3] if len(sys.argv) > 3 else secrets.token_urlsafe(9)
    data = open(inp, "rb").read()
    salt, iv, ct = encrypt(data, pw)
    html = (GATE.replace("__SALT__", salt).replace("__IV__", iv)
                .replace("__CT__", ct).replace("__ITER__", str(ITER)))
    open(outp, "w").write(html)
    print("PASSWORD=" + pw)
    print("wrote " + outp + " (" + str(len(html)) + " bytes)")

if __name__ == "__main__":
    main()
