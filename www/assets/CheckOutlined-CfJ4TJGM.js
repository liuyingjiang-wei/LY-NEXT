import{r as i,R as L,g as A}from"./index-w86uI7oV.js";import{h as W,at as X,bj as G,bk as z,bl as J,bm as Q,ae as Y,c as Z,bn as ee,bo as te,X as $,A as ne}from"./apiClient-CTUg0eIE.js";import"./index-D9xqZtZt.js";function F(e,t=!1){if(X(e)){const n=e.nodeName.toLowerCase(),o=["input","select","textarea","button"].includes(n)||e.isContentEditable||n==="a"&&!!e.getAttribute("href"),r=e.getAttribute("tabindex"),s=Number(r);let a=null;return r&&!Number.isNaN(s)?a=s:o&&a===null&&(a=0),o&&e.disabled&&(a=null),a!==null&&(a>=0||t&&a<0)}return!1}function _(e,t=!1){const n=[...e.querySelectorAll("*")].filter(o=>F(o,t));return F(e,t)&&n.unshift(e),n}function Re(e,t){if(!e)return;e.focus(t);const{cursor:n}=t||{};if(n&&(e instanceof HTMLInputElement||e instanceof HTMLTextAreaElement)){const o=e.value.length;switch(n){case"start":e.setSelectionRange(0,0);break;case"end":e.setSelectionRange(o,o);break;default:e.setSelectionRange(0,o)}}}let f=null,u=[];const w=new Map,O=new Map;function k(){return u[u.length-1]}function oe(e){const t=k();if(e&&t){let n;for(const[r,s]of w.entries())if(s===t){n=r;break}const o=O.get(n);return!!o&&(o===e||o.contains(e))}return!1}function re(e){const{activeElement:t}=document;return e===t||e.contains(t)}function v(){const e=k(),{activeElement:t}=document;if(!oe(t))if(e&&!re(e)){const n=_(e);(n.includes(f)?f:n[0])?.focus({preventScroll:!0})}else f=t}function I(e){if(e.key==="Tab"){const{activeElement:t}=document,n=k(),o=_(n),r=o[o.length-1];e.shiftKey&&t===o[0]?f=r:!e.shiftKey&&t===r&&(f=o[0])}}function se(e,t){return e&&(w.set(t,e),u=u.filter(n=>n!==e),u.push(e),window.addEventListener("focusin",v),window.addEventListener("keydown",I,!0),v()),()=>{f=null,u=u.filter(n=>n!==e),w.delete(t),O.delete(t),u.length===0&&(window.removeEventListener("focusin",v),window.removeEventListener("keydown",I,!0))}}function ae(e,t){const n=i.useRef(0),[o,r]=i.useState(0);i.useEffect(()=>{n.current=0},t),i.useEffect(()=>{const[s,a]=e(n.current);return a||(n.current+=1,r(l=>l+1)),s},[...t,o])}function Oe(e,t){const n=W(),o=i.useRef(t);return o.current=t,ae(a=>{if(!e)return[void 0,!0];const l=o.current();return l?[se(l,n),!0]:[void 0,a>=1]},[n,e]),[a=>{a&&O.set(n,a)}]}function ie(e){return e.replace(/-(.)/g,(t,n)=>n.toUpperCase())}function ce(e,t){Y(e,`[@ant-design/icons] ${t}`)}function S(e){return typeof e=="object"&&typeof e.name=="string"&&typeof e.theme=="string"&&(typeof e.icon=="object"||typeof e.icon=="function")}function j(e={}){return Object.keys(e).reduce((t,n)=>{const o=e[n];return n==="class"?(t.className=o,delete t.class):(delete t[n],t[ie(n)]=o),t},{})}function E(e,t,n){return n?L.createElement(e.tag,{key:t,...j(e.attrs),...n},(e.children||[]).map((o,r)=>E(o,`${t}-${e.tag}-${r}`))):L.createElement(e.tag,{key:t,...j(e.attrs)},(e.children||[]).map((o,r)=>E(o,`${t}-${e.tag}-${r}`)))}function P(e){return G(e)[0]}function q(e){return e?Array.isArray(e)?e:[e]:[]}const le=`
.anticon {
  display: inline-flex;
  align-items: center;
  color: inherit;
  font-style: normal;
  line-height: 0;
  text-align: center;
  text-transform: none;
  vertical-align: -0.125em;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.anticon > * {
  line-height: 1;
}

.anticon svg {
  display: inline-block;
  vertical-align: inherit;
}

.anticon::before {
  display: none;
}

.anticon .anticon-icon {
  display: block;
}

.anticon[tabindex] {
  cursor: pointer;
}

.anticon-spin {
  -webkit-animation: loadingCircle 1s infinite linear;
  animation: loadingCircle 1s infinite linear;
}

@-webkit-keyframes loadingCircle {
  100% {
    -webkit-transform: rotate(360deg);
    transform: rotate(360deg);
  }
}

@keyframes loadingCircle {
  100% {
    -webkit-transform: rotate(360deg);
    transform: rotate(360deg);
  }
}
`,ue=e=>{const{csp:t,prefixCls:n,layer:o}=i.useContext(z);let r=le;n&&(r=r.replace(/anticon/g,n)),o&&(r=`@layer ${o} {
${r}
}`),i.useEffect(()=>{const s=e.current,a=J(s);Q(r,"@ant-design-icons",{prepend:!o,csp:t,attachTo:a})},[])},m={primaryColor:"#333",secondaryColor:"#E6E6E6",calculated:!1};function fe({primaryColor:e,secondaryColor:t}){m.primaryColor=e,m.secondaryColor=t||P(e),m.calculated=!!t}function de(){return{...m}}const d=e=>{const{icon:t,className:n,onClick:o,style:r,primaryColor:s,secondaryColor:a,...l}=e,C=i.useRef(null);let g=m;if(s&&(g={primaryColor:s,secondaryColor:a||P(s)}),ue(C),ce(S(t),`icon should be icon definiton, but got ${t}`),!S(t))return null;let c=t;return c&&typeof c.icon=="function"&&(c={...c,icon:c.icon(g.primaryColor,g.secondaryColor)}),E(c.icon,`svg-${c.name}`,{className:n,onClick:o,style:r,"data-icon":c.name,width:"1em",height:"1em",fill:"currentColor","aria-hidden":"true",...l,ref:C})};d.displayName="IconReact";d.getTwoToneColors=de;d.setTwoToneColors=fe;function B(e){const[t,n]=q(e);return d.setTwoToneColors({primaryColor:t,secondaryColor:n})}function ge(){const e=d.getTwoToneColors();return e.calculated?[e.primaryColor,e.secondaryColor]:e.primaryColor}function x(){return x=Object.assign?Object.assign.bind():function(e){for(var t=1;t<arguments.length;t++){var n=arguments[t];for(var o in n)Object.prototype.hasOwnProperty.call(n,o)&&(e[o]=n[o])}return e},x.apply(this,arguments)}B(ee.primary);const h=i.forwardRef((e,t)=>{const{className:n,icon:o,spin:r,rotate:s,tabIndex:a,onClick:l,twoToneColor:C,...g}=e,{prefixCls:c="anticon",rootClassName:D}=i.useContext(z),H=Z(D,c,{[`${c}-${o.name}`]:!!o.name,[`${c}-spin`]:!!r||o.name==="loading"},n);let y=a;y===void 0&&l&&(y=-1);const K=s?{msTransform:`rotate(${s}deg)`,transform:`rotate(${s}deg)`}:void 0,[V,U]=q(C);return i.createElement("span",x({role:"img","aria-label":o.name},g,{ref:t,tabIndex:y,onClick:l,className:H}),i.createElement(d,{icon:o,primaryColor:V,secondaryColor:U,style:K}))});h.getTwoToneColor=ge;h.setTwoToneColor=B;var p={},M;function me(){if(M)return p;M=1,Object.defineProperty(p,"__esModule",{value:!0});var e={icon:{tag:"svg",attrs:{"fill-rule":"evenodd",viewBox:"64 64 896 896",focusable:"false"},children:[{tag:"path",attrs:{d:"M512 64c247.4 0 448 200.6 448 448S759.4 960 512 960 64 759.4 64 512 264.6 64 512 64zm127.98 274.82h-.04l-.08.06L512 466.75 384.14 338.88c-.04-.05-.06-.06-.08-.06a.12.12 0 00-.07 0c-.03 0-.05.01-.09.05l-45.02 45.02a.2.2 0 00-.05.09.12.12 0 000 .07v.02a.27.27 0 00.06.06L466.75 512 338.88 639.86c-.05.04-.06.06-.06.08a.12.12 0 000 .07c0 .03.01.05.05.09l45.02 45.02a.2.2 0 00.09.05.12.12 0 00.07 0c.02 0 .04-.01.08-.05L512 557.25l127.86 127.87c.04.04.06.05.08.05a.12.12 0 00.07 0c.03 0 .05-.01.09-.05l45.02-45.02a.2.2 0 00.05-.09.12.12 0 000-.07v-.02a.27.27 0 00-.05-.06L557.25 512l127.87-127.86c.04-.04.05-.06.05-.08a.12.12 0 000-.07c0-.03-.01-.05-.05-.09l-45.02-45.02a.2.2 0 00-.09-.05.12.12 0 00-.07 0z"}}]},name:"close-circle",theme:"filled"};return p.default=e,p}var Ce=me();const pe=A(Ce);function T(){return T=Object.assign?Object.assign.bind():function(e){for(var t=1;t<arguments.length;t++){var n=arguments[t];for(var o in n)Object.prototype.hasOwnProperty.call(n,o)&&(e[o]=n[o])}return e},T.apply(this,arguments)}const be=(e,t)=>i.createElement(h,T({},e,{ref:t,icon:pe})),ke=i.forwardRef(be),Le=(e,t)=>{const n=i.useContext(te),o=i.useMemo(()=>{const s=t||$[e],a=n?.[e]??{};return{...ne(s)?s():s,...a||{}}},[e,t,n]),r=i.useMemo(()=>{const s=n?.locale;return n?.exist&&!s?$.locale:s},[n]);return[o,r]};var b={},N;function he(){if(N)return b;N=1,Object.defineProperty(b,"__esModule",{value:!0});var e={icon:{tag:"svg",attrs:{viewBox:"64 64 896 896",focusable:"false"},children:[{tag:"path",attrs:{d:"M912 190h-69.9c-9.8 0-19.1 4.5-25.1 12.2L404.7 724.5 207 474a32 32 0 00-25.1-12.2H112c-6.7 0-10.4 7.7-6.3 12.9l273.9 347c12.8 16.2 37.4 16.2 50.3 0l488.4-618.9c4.1-5.1.4-12.8-6.3-12.8z"}}]},name:"check",theme:"outlined"};return b.default=e,b}var ye=he();const ve=A(ye);function R(){return R=Object.assign?Object.assign.bind():function(e){for(var t=1;t<arguments.length;t++){var n=arguments[t];for(var o in n)Object.prototype.hasOwnProperty.call(n,o)&&(e[o]=n[o])}return e},R.apply(this,arguments)}const we=(e,t)=>i.createElement(h,R({},e,{ref:t,icon:ve})),$e=i.forwardRef(we);export{h as I,ke as R,Le as a,$e as b,_ as g,Re as t,Oe as u};
