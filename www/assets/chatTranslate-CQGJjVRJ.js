const l=`你是一名专业翻译。请将以下文本翻译为 {target_language}。
保留 Markdown 格式、代码块与行内代码；只输出译文，不要解释、不要加标题。

原文：
{text}`,n=[{id:"en",label:"English",flag:"🇺🇸",target:"English"},{id:"zh-CN",label:"简体中文",flag:"🇨🇳",target:"简体中文"},{id:"zh-TW",label:"繁体中文",flag:"🇹🇼",target:"繁体中文"},{id:"ja",label:"日语",flag:"🇯🇵",target:"日语"},{id:"ko",label:"韩语",flag:"🇰🇷",target:"韩语"},{id:"fr",label:"法语",flag:"🇫🇷",target:"法语"},{id:"de",label:"德语",flag:"🇩🇪",target:"德语"},{id:"it",label:"意大利语",flag:"🇮🇹",target:"意大利语"}];function f(){return{mode:"chat",prompt:l,languages:n}}function r(a){return String(a?.prompt||"").trim()||l}function o(a,{targetLanguage:t,text:e}){return r({prompt:a}).replace(/\{target_language\}/g,t).replace(/\{text\}/g,e)}function g(a,t){return(a||n).find(e=>e.id===t)}function s(a,t){const e=g(t,a);return e?e.label:a||""}export{l as D,n as a,o as b,f as d,g as f,s as l};
