import"./modulepreload-polyfill-B5Qt9EMX.js";import{r as c,j as e,c as ce}from"./vendor-react-DcvSQIho.js";import{p as V}from"./motionPrefs-B-xs_S1I.js";import{R as le,P as ue,T as fe,M as de}from"./vendor-ogl-DfWMHKQ0.js";import{g as f,S as X}from"./vendor-gsap-a3sj5zmn.js";function me(t,n,r,o){return`M ${t-r} ${n} A ${r} ${o} 0 1 0 ${t+r} ${n} A ${r} ${o} 0 1 0 ${t-r} ${n}`}function he({index:t,totalItems:n,path:r,itemSize:o,rotation:i,fill:a,duration:g,direction:v,paused:m,reducedMotion:p,children:b}){const l=a&&n>0?-(t/n*g):0;return e.jsx("div",{className:"orbit-item",style:{"--orbit-duration":`${g}s`,"--orbit-delay":`${l}s`,"--orbit-direction":v==="reverse"?"reverse":"normal",width:o,height:o,offsetPath:`path("${r}")`,offsetRotate:"0deg",offsetAnchor:"center center",offsetDistance:"0%",animationPlayState:m||p?"paused":"running"},children:e.jsx("div",{className:"orbit-item__inner",style:{transform:`rotate(${-i}deg)`},children:b})})}function ve({images:t=[],altPrefix:n="Orbiting image",baseWidth:r=1400,radiusX:o=700,radiusY:i=170,rotation:a=-8,duration:g=40,itemSize:v=64,direction:m="normal",fill:p=!0,width:b="100%",height:l="100%",className:x="",showPath:C=!1,pathColor:M="rgba(255,255,255,0.08)",pathWidth:N=2,paused:E=!1,centerContent:F,responsive:h=!1}){const y=c.useRef(null),[G,A]=c.useState(1),[$,O]=c.useState(!0),[B,L]=c.useState(!1),H=V(),P=r/2,I=r/2,R=c.useMemo(()=>me(P,I,o,i),[P,I,o,i]);c.useEffect(()=>{if(!h||!y.current)return;let s=0;const u=()=>{y.current&&A(y.current.clientWidth/r)},_=()=>{cancelAnimationFrame(s),s=requestAnimationFrame(u)};u();const q=new ResizeObserver(_);return q.observe(y.current),()=>{cancelAnimationFrame(s),q.disconnect()}},[h,r]),c.useEffect(()=>{const s=()=>L(document.hidden);return s(),document.addEventListener("visibilitychange",s),()=>document.removeEventListener("visibilitychange",s)},[]),c.useEffect(()=>{const s=y.current;if(!s||typeof IntersectionObserver>"u")return;const u=new IntersectionObserver(([_])=>O(_.isIntersecting),{root:null,threshold:.08,rootMargin:"80px 0px"});return u.observe(s),()=>u.disconnect()},[]);const S=E||B||!$,w=t.length;return e.jsxs("div",{ref:y,className:`orbit-container ${x}`.trim(),style:{width:h?"100%":b,height:h?"auto":l,aspectRatio:h?"1 / 1":void 0},"aria-hidden":F?void 0:!0,children:[e.jsx("div",{className:h?"orbit-scaling-container orbit-scaling-container--responsive":"orbit-scaling-container",style:{width:h?r:"100%",height:h?r:"100%",transform:h?`translate(-50%, -50%) scale(${G})`:void 0},children:e.jsxs("div",{className:"orbit-rotation-wrapper",style:{transform:`rotate(${a}deg)`},children:[C?e.jsx("svg",{width:"100%",height:"100%",viewBox:`0 0 ${r} ${r}`,className:"orbit-path-svg","aria-hidden":!0,children:e.jsx("path",{d:R,fill:"none",stroke:M,strokeWidth:N/Math.max(G,.01)})}):null,t.map((s,u)=>e.jsx(he,{index:u,totalItems:w,path:R,itemSize:v,rotation:a,fill:p,duration:g,direction:m,paused:S,reducedMotion:H,children:e.jsx("img",{src:s,alt:`${n} ${u+1}`,width:v,height:v,draggable:!1,decoding:"async",loading:u<2?"eager":"lazy",fetchPriority:u===0?"high":"auto",className:"orbit-image"})},s))]})}),F?e.jsx("div",{className:"orbit-center-content",children:F}):null]})}const ee=8,ie=t=>{const n=t.replace("#","").padEnd(6,"0"),r=parseInt(n.slice(0,2),16)/255,o=parseInt(n.slice(2,4),16)/255,i=parseInt(n.slice(4,6),16)/255;return[r,o,i]},ge=t=>{const n=(t&&t.length?t:["#A6C8FF","#5227FF","#FF9FFC"]).slice(0,ee),r=n.length,o=[];for(let a=0;a<ee;a+=1)o.push(ie(n[Math.min(a,n.length-1)]));const i=[0,0,0];for(let a=0;a<r;a+=1)i[0]+=o[a][0],i[1]+=o[a][1],i[2]+=o[a][2];return i[0]/=r,i[1]/=r,i[2]/=r,{arr:o,count:r,avg:i}},pe=`
attribute vec2 position;
attribute vec2 uv;
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position, 0.0, 1.0);
}
`,xe=`
precision highp float;

uniform vec3  iResolution;
uniform vec2  iMouse;
uniform float iTime;

uniform vec3  uColor0;
uniform vec3  uColor1;
uniform vec3  uColor2;
uniform vec3  uColor3;
uniform vec3  uColor4;
uniform vec3  uColor5;
uniform vec3  uColor6;
uniform vec3  uColor7;
uniform int   uColorCount;

uniform vec3  uBgColor;
uniform vec3  uMouseColor;
uniform float uSpeed;
uniform int   uStreakCount;
uniform float uStreakWidth;
uniform float uStreakLength;
uniform float uGlow;
uniform float uDensity;
uniform float uTwinkle;
uniform float uZoom;
uniform float uBgGlow;
uniform float uOpacity;
uniform float uMouseEnabled;
uniform float uMouseStrength;
uniform float uMouseRadius;

varying vec2 vUv;

vec3 palette(float h) {
  int count = uColorCount;
  if (count < 1) count = 1;
  int idx = int(floor(clamp(h, 0.0, 0.999999) * float(count)));
  if (idx <= 0) return uColor0;
  if (idx == 1) return uColor1;
  if (idx == 2) return uColor2;
  if (idx == 3) return uColor3;
  if (idx == 4) return uColor4;
  if (idx == 5) return uColor5;
  if (idx == 6) return uColor6;
  return uColor7;
}

vec3 tanhv(vec3 x) {
  vec3 e = exp(-2.0 * x);
  return (1.0 - e) / (1.0 + e);
}

vec2 sceneC(vec2 frag, vec2 r) {
  vec2 P = (frag + frag - r) / r.x;
  float z = 0.0;
  float d = 1e3;
  vec4 O = vec4(0.0);
  for (int k = 0; k < 39; k++) {
    if (d <= 1e-4) break;
    O = z * normalize(vec4(P, uZoom, 0.0)) - vec4(0.0, 4.0, 1.0, 0.0) / 4.5;
    d = 1.0 - sqrt(length(O * O));
    z += d;
  }
  return vec2(O.x, atan(O.z, O.y));
}

void mainImage(out vec4 o, vec2 C) {
  vec2 r = iResolution.xy;
  vec2 uv0 = (C + C - r) / r.x;
  float T = 0.1 * iTime * uSpeed + 9.0;
  float angRings = max(1.0, floor(6.28318530718 * max(uDensity, 0.05) + 0.5));
  vec2 Y = vec2(5e-3, 6.28318530718 / angRings);

  vec2 c0 = sceneC(C, r);
  vec2 cdx = sceneC(C + vec2(1.0, 0.0), r);
  vec2 cdy = sceneC(C + vec2(0.0, 1.0), r);
  vec2 dCx = cdx - c0;
  vec2 dCy = cdy - c0;
  dCx.y -= 6.28318530718 * floor(dCx.y / 6.28318530718 + 0.5);
  dCy.y -= 6.28318530718 * floor(dCy.y / 6.28318530718 + 0.5);
  vec2 fw = abs(dCx) + abs(dCy);
  C = c0;

  vec2 P = vec2(2.0, 1.0) * uv0 - (r / r.x) * vec2(0.0, 1.0);
  vec4 O = vec4(uBgColor * 90.0 * uBgGlow / (1e3 * dot(P, P) + 6.0), 0.0);

  float mGlow = 0.0;
  if (uMouseEnabled > 0.5) {
    vec2 mN = (iMouse + iMouse - r) / r.x;
    float md = length(uv0 - mN);
    mGlow = exp(-md * md / max(uMouseRadius * uMouseRadius, 1e-4)) * uMouseStrength;
    O.rgb += uMouseColor * mGlow * 0.25;
  }

  float zr = 5e-4 * uStreakWidth;
  vec2 rr = vec2(max(length(fw), 1e-5));
  float tail = 19.0 / max(uStreakLength, 0.05);

  for (int m = 0; m < 16; m++) {
    if (m >= uStreakCount) break;
    float jf = float(m) + 1.0;
    float ic = fract(sin(dot(vec2(jf, floor(C.x / Y.x + 0.5)), vec2(7.0, 11.0)) * 73.0));
    vec2 Pp = C - (T + T * ic) * vec2(0.0, 1.0);
    Pp -= floor(Pp / Y + 0.5) * Y;
    float h = fract(8663.0 * ic);
    vec3 col = palette(h);
    float weight = mix(1.5, 1.0 + sin(T + 7.0 * h + 4.0), uTwinkle);
    weight *= (1.0 + mGlow * 2.0);
    vec2 inner = vec2(length(max(Pp, vec2(-1.0, 0.0))), length(Pp) - zr) - zr;
    vec2 sm = vec2(1.0) - smoothstep(-rr, rr, inner);
    O.rgb += dot(sm, vec2(exp(tail * Pp.y), 3.0)) * col * weight;
    C.x += Y.x / 8.0;
  }

  vec3 colr = sqrt(tanhv(max(O.rgb * uGlow - vec3(0.04, 0.08, 0.02), 0.0)));
  o = vec4(colr, uOpacity);
}

void main() {
  vec4 color;
  mainImage(color, vUv * iResolution.xy);
  gl_FragColor = color;
}
`;function Ce({className:t="",dpr:n,paused:r=!1,colors:o=["#A6C8FF","#5227FF","#FF9FFC"],backgroundColor:i="#050818",speed:a=.5,streakCount:g=2,streakWidth:v=1,streakLength:m=1,glow:p=1,density:b=.6,twinkle:l=1,zoom:x=3,backgroundGlow:C=.45,opacity:M=1,mouseInteraction:N=!0,mouseStrength:E=.5,mouseRadius:F=1,mouseDampening:h=.15,mixBlendMode:y}){const G=c.useRef(null),A=c.useRef(null),$=c.useRef(null),O=c.useRef(null),B=c.useRef(null),L=c.useRef(null),H=c.useRef([0,0]),P=c.useRef(0),I=V();return c.useEffect(()=>{const R=G.current;if(!R||I)return;const S=new le({dpr:n??(typeof window<"u"&&window.devicePixelRatio||1),alpha:!0,antialias:!0});L.current=S;const{gl:w}=S,{canvas:s}=w;s.style.width="100%",s.style.height="100%",s.style.display="block",R.appendChild(s);const{arr:u,count:_,avg:q}=ge(o),Y={iResolution:{value:[w.drawingBufferWidth,w.drawingBufferHeight,1]},iMouse:{value:[0,0]},iTime:{value:0},uColor0:{value:u[0]},uColor1:{value:u[1]},uColor2:{value:u[2]},uColor3:{value:u[3]},uColor4:{value:u[4]},uColor5:{value:u[5]},uColor6:{value:u[6]},uColor7:{value:u[7]},uColorCount:{value:_},uBgColor:{value:ie(i)},uMouseColor:{value:q},uSpeed:{value:a},uStreakCount:{value:Math.max(1,Math.min(16,Math.round(g)))},uStreakWidth:{value:v},uStreakLength:{value:m},uGlow:{value:p},uDensity:{value:b},uTwinkle:{value:l},uZoom:{value:x},uBgGlow:{value:C},uOpacity:{value:M},uMouseEnabled:{value:N?1:0},uMouseStrength:{value:E},uMouseRadius:{value:F}},W=new ue(w,{vertex:pe,fragment:xe,uniforms:Y});$.current=W;const Z=new fe(w);B.current=Z;const se=new de(w,{geometry:Z,program:W});O.current=se;const D=()=>{const d=R.getBoundingClientRect();S.setSize(d.width,d.height),Y.iResolution.value=[w.drawingBufferWidth,w.drawingBufferHeight,1]};D();const Q=new ResizeObserver(D);Q.observe(R);const J=d=>{const j=s.getBoundingClientRect(),T=S.dpr||1,k=(d.clientX-j.left)*T,z=(j.height-(d.clientY-j.top))*T;H.current=[k,z],h<=0&&(Y.iMouse.value=[k,z])};N&&s.addEventListener("pointermove",J);const K=d=>{if(A.current=requestAnimationFrame(K),Y.iTime.value=d*.001,h>0){P.current||(P.current=d);const j=(d-P.current)/1e3;P.current=d;const T=Math.max(1e-4,h);let k=1-Math.exp(-j/T);k>1&&(k=1);const z=H.current,U=Y.iMouse.value;U[0]+=(z[0]-U[0])*k,U[1]+=(z[1]-U[1])*k}else P.current=d;if(!r&&$.current&&O.current)try{S.render({scene:O.current})}catch{}};return A.current=requestAnimationFrame(K),()=>{A.current&&cancelAnimationFrame(A.current),N&&s.removeEventListener("pointermove",J),Q.disconnect(),s.parentElement===R&&R.removeChild(s);const d=(j,T)=>{j&&typeof j[T]=="function"&&j[T].call(j)};d($.current,"remove"),d(B.current,"remove"),d(O.current,"remove"),d(L.current,"destroy"),$.current=null,B.current=null,O.current=null,L.current=null}},[n,r,o,i,a,g,v,m,p,b,l,x,C,M,N,E,F,h,I]),I?e.jsx("div",{className:`lightfall-container lightfall-container--static ${t}`.trim(),style:{background:`radial-gradient(ellipse 90% 70% at 50% 20%, ${i} 0%, #09090b 70%)`,...y&&{mixBlendMode:y}}}):e.jsx("div",{ref:G,className:`lightfall-container ${t}`.trim(),style:{...y&&{mixBlendMode:y}}})}let te=!1;function ae(){te||typeof window>"u"||(f.registerPlugin(X),te=!0)}ae();function re({children:t,scrollContainerRef:n,enableBlur:r=!1,baseOpacity:o=.2,baseRotation:i=2,blurStrength:a=3,containerClassName:g="",textClassName:v="",as:m="h2"}){const p=c.useRef(null),b=c.useMemo(()=>(typeof t=="string"?t:"").split(/(\s+)/).map((x,C)=>x.match(/^\s+$/)?x:e.jsx("span",{className:"word",children:x},C)),[t]);return c.useEffect(()=>{const l=p.current;if(!l||typeof t!="string")return;const x=n&&n.current?n.current:window,C=l.querySelectorAll(".word"),M=()=>{if(V()){f.set(l,{rotate:0,clearProps:"transform"}),f.set(C,{opacity:1,filter:"none",clearProps:"opacity,filter"});return}f.to(l,{rotate:0,duration:.55,ease:"power2.out",transformOrigin:"0% 50%",overwrite:"auto"}),f.to(C,{opacity:1,filter:"none",duration:.5,stagger:.035,ease:"power2.out",overwrite:"auto",onComplete:()=>{f.set(C,{clearProps:"opacity,filter"}),f.set(l,{clearProps:"transform"})}})};f.set(l,{transformOrigin:"0% 50%",rotate:i}),f.set(C,{opacity:o,filter:r?`blur(${a}px)`:"none"});const N=f.context(()=>{X.create({trigger:l,scroller:x,start:"top 90%",once:!0,onEnter:M}),requestAnimationFrame(()=>{X.refresh();const E=l.getBoundingClientRect();E.top<window.innerHeight*.9&&E.bottom>0&&M()})},l);return()=>N.revert()},[t,n,r,i,o,a]),e.jsx(m,{ref:p,className:`scroll-reveal ${g}`,children:e.jsx("p",{className:`scroll-reveal-text ${v}`,children:b})})}ae();function ye(t){if(V()){f.set(t,{opacity:1,y:0,rotate:0,filter:"none",clearProps:"all"}),t.children.length&&f.set(t.children,{opacity:1,y:0,clearProps:"all"});return}f.to(t,{opacity:1,y:0,rotate:0,filter:"none",duration:.55,ease:"power2.out",overwrite:"auto",onComplete:()=>{f.set(t,{clearProps:"filter,transform,opacity"})}}),t.children.length>1&&f.from(t.children,{opacity:0,y:20,duration:.48,stagger:.075,ease:"power2.out",delay:.08,overwrite:"auto",onComplete:()=>{f.set(t.children,{clearProps:"opacity,transform"})}})}function ne({children:t,className:n="",baseRotation:r=2,baseOpacity:o=.35,enableBlur:i=!1,blurStrength:a=6,yOffset:g=36}){const v=c.useRef(null);return c.useEffect(()=>{const m=v.current;if(!m)return;f.set(m,{opacity:o,y:g,rotate:r,transformOrigin:"50% 20%",filter:i?`blur(${a}px)`:"none"});const p=()=>ye(m),b=f.context(()=>{X.create({trigger:m,start:"top 90%",once:!0,onEnter:p}),requestAnimationFrame(()=>{X.refresh();const l=m.getBoundingClientRect();l.top<window.innerHeight*.9&&l.bottom>0&&p()})},m);return()=>b.revert()},[r,o,i,a,g]),e.jsx("div",{ref:v,className:n,children:t})}const be=6,we="webp".replace(/^\./,""),je="/ly/static/orbit";function Re(t){return`${je}/orbit-${t}.${we}`}function Ne(){return Array.from({length:be},(t,n)=>Re(n+1))}const Pe=Ne(),Me=[{id:"gitee",title:"Gitee 仓库",desc:"国内访问友好，适合镜像与协作开发。",url:"https://gitee.com/wei2335/LY-NEXT",accent:"gitee"},{id:"github",title:"GitHub 仓库",desc:"国际主仓库，Issue / PR 与开源协作入口。",url:"https://github.com/liuyingjiang-wei/LY-NEXT",accent:"github"},{id:"gitcode",title:"GitCode 仓库",desc:"GitCode 托管镜像，便于国内开发者拉取。",url:"https://gitcode.com/liuyingjiang/ly-next",accent:"gitcode"}],Ee=[{title:"极速响应",desc:"基于 FastAPI 与 LangGraph 的高效 Agent 运行时。"},{title:"多 Agent 模式",desc:"ReAct、Plan-then-Act、Coordinator 与 Chat 灵活切换。"},{title:"MCP 与工具",desc:"内置工具注册表，可暴露 MCP Server 并接入远端 MCP。"},{title:"多模型路由",desc:"OpenAI、Anthropic、Ollama 及 OpenAI 兼容网关。"},{title:"工作台与桥接",desc:"Web 控制台、会话持久化与 OneBot v11 桥接。"}],Fe=["ReAct","Plan","MCP","MIT"];function oe(){if(typeof document>"u"||document.querySelector('link[rel="prefetch"][href="/firefly"]'))return;const t=document.createElement("link");t.rel="prefetch",t.href="/firefly",document.head.appendChild(t)}function Oe(){return e.jsxs("div",{className:"home-page",children:[e.jsx("div",{className:"home-lightfall","aria-hidden":!0,children:e.jsx(Ce,{colors:["#A6C8FF","#5227FF","#FF9FFC"],backgroundColor:"#050818",speed:.5,streakCount:2,streakWidth:1,streakLength:1,glow:1,density:.6,twinkle:1,zoom:3,backgroundGlow:.45,opacity:1,mouseInteraction:!0,mouseStrength:.5,mouseRadius:1})}),e.jsxs("header",{className:"home-topbar",children:[e.jsxs("a",{className:"home-brand",href:"/",children:[e.jsx("img",{className:"home-brand-mark",src:"/ly/static/brand/tubiao.jpg",alt:"",loading:"eager",decoding:"async"}),"LY-NEXT"]}),e.jsxs("nav",{className:"home-topnav","aria-label":"主导航",children:[e.jsx("a",{className:"home-nav-link",href:"#hero",children:"概览"}),e.jsx("a",{className:"home-nav-link",href:"/firefly",onMouseEnter:oe,onFocus:oe,children:"流萤"}),e.jsx("a",{className:"home-nav-link",href:"#repos",children:"仓库"}),e.jsx("a",{className:"home-nav-link",href:"#features",children:"特性"})]})]}),e.jsxs("main",{children:[e.jsx("section",{id:"hero",className:"home-hero",children:e.jsxs("div",{className:"home-hero-stage",children:[e.jsx("div",{className:"home-orbit-wrap",children:e.jsx(ve,{images:Pe,shape:"ellipse",baseWidth:3200,radiusX:1520,radiusY:420,rotation:-8,duration:36,itemSize:376,responsive:!0,direction:"normal",fill:!0,showPath:!0,pathColor:"rgba(250, 204, 21, 0.22)",pathWidth:3,centerContent:e.jsxs("div",{className:"home-center-copy",children:[e.jsx("h1",{className:"home-title",children:"LY-NEXT"}),e.jsx("p",{className:"home-tagline",children:"基于 FastAPI 与 LangGraph 的智能体服务，内置 Web 工作台与可选 PostgreSQL / Redis。"}),e.jsx("ul",{className:"home-hero-tags",children:Fe.map(t=>e.jsx("li",{children:t},t))})]})})}),e.jsxs("div",{className:"home-hero-actions",children:[e.jsx("a",{className:"home-btn home-btn--primary",href:"/ly/",children:"进入工作台"}),e.jsx("a",{className:"home-btn home-btn--ghost",href:"/ly/login",children:"登录"})]})]})}),e.jsxs("section",{id:"repos",className:"home-section home-section--panel",children:[e.jsx("div",{className:"home-section-heading",children:e.jsx(re,{baseOpacity:.35,enableBlur:!1,baseRotation:0,containerClassName:"home-scroll-reveal-title",textClassName:"home-scroll-reveal-title-text",children:"项目仓库"})}),e.jsx(ne,{className:"home-repo-grid",enableBlur:!1,children:Me.map(t=>e.jsxs("article",{className:`home-repo-card home-repo-card--${t.accent}`,children:[e.jsx("h3",{children:t.title}),e.jsx("p",{children:t.desc}),e.jsx("a",{className:"home-repo-link",href:t.url,target:"_blank",rel:"noopener noreferrer",children:"立即访问 →"})]},t.id))})]}),e.jsxs("section",{id:"features",className:"home-section home-section--panel",children:[e.jsx("div",{className:"home-section-heading",children:e.jsx(re,{baseOpacity:.35,enableBlur:!1,baseRotation:0,containerClassName:"home-scroll-reveal-title",textClassName:"home-scroll-reveal-title-text",children:"核心特性"})}),e.jsx(ne,{className:"home-feature-grid",enableBlur:!1,baseRotation:0,yOffset:16,children:Ee.map(t=>e.jsxs("article",{className:"home-feature-card",children:[e.jsx("h3",{children:t.title}),e.jsx("p",{children:t.desc})]},t.title))})]})]}),e.jsxs("footer",{id:"about",className:"home-footer",children:[e.jsx("p",{children:"LY-NEXT · Agent Service · MIT License"}),e.jsxs("p",{className:"home-footer-links",children:[e.jsx("a",{href:"https://github.com/liuyingjiang-wei/LY-NEXT",target:"_blank",rel:"noopener noreferrer",children:"GitHub"}),e.jsx("span",{"aria-hidden":!0,children:"·"}),e.jsx("a",{href:"https://gitee.com/wei2335/LY-NEXT",target:"_blank",rel:"noopener noreferrer",children:"Gitee"}),e.jsx("span",{"aria-hidden":!0,children:"·"}),e.jsx("a",{href:"https://gitcode.com/liuyingjiang/ly-next",target:"_blank",rel:"noopener noreferrer",children:"GitCode"})]})]})]})}ce.createRoot(document.getElementById("root")).render(e.jsx(Oe,{}));
