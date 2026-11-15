import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
const languages=['zh-CN','zh-TW','en','hi'];
// Chinese copy must stay Chinese: no Devanagari (U+0900–U+097F, the block that
// carries the Hindi sentence terminator ।/॥) may leak into a zh value, and a
// Chinese sentence must not end on a character belonging to some other writing
// system (see `languageScriptTerminator`), nor on a half-width terminator.
const devanagari=/[ऀ-ॿ]/;
const cjkTerminator=/[　-〿㐀-䶿一-鿿＀-￯]/;
// `Non-Chinese sentence terminator` scope: a zh value is rejected only when its
// final character belongs to a natural-language writing system other than the
// Chinese ones — a terminator that shows the copy drifted into another language
// (`用量 ↑` is fine, `…あ`, `…한`, `…ا`, `…Ж`, `…é` are not). Membership is decided
// by the Unicode Script property, never by "anything outside the CJK ranges", so
// symbols, units and typographic marks — all Script=Common — are accepted with no
// entry anywhere: ℃ ° ½ ¼ ™ ® ↑ ↓ ← → ✔ … · × — – “ ” ‘ ’ ・, plus the full-width
// forms ：？！（） via `cjkTerminator`. That also removes the old whitelist's
// inconsistency (`→ ←` were listed, `↑ ↓` were not) without going back to
// enumerating symbols.
// Deliberately absent from `languageScripts`: Han / Bopomofo / Tangut (the copy's
// own scripts) and Greek, because Greek letters are the ordinary unit and math
// symbols of technical support copy (电阻 10Ω, 圆周率 π, 精度 5μ) while a Greek
// sentence leaking into a zh string is not a failure mode of a zh/zh-TW/en/hi
// product — add 'Greek' to the list if that ever changes. Known residual: Å/å
// (U+212B/U+00E5, Script=Latin) still reads as a foreign terminator even as a
// length unit; no dictionary uses it, and `neutralFinal` is the place to exempt it.
// Corpus audit over all 2075 keys of both zh dictionaries (2026-11-13): 42 values
// (21 per locale) end on a character that is neither printable ASCII nor inside
// the CJK ranges — `…` ×34, `→` ×6, `·` ×2, all Script=Common — so this narrowing
// turns no currently-green copy red and rejects no copy the old rule accepted.
const languageScripts=['Latin','Cyrillic','Arabic','Hebrew','Devanagari','Bengali','Gurmukhi','Gujarati','Oriya','Tamil','Telugu','Kannada','Malayalam','Sinhala','Hiragana','Katakana','Hangul','Thai','Lao','Khmer','Myanmar','Georgian','Armenian','Ethiopic','Cherokee','Mongolian','Syriac','Nko','Tifinagh','Vai','Thaana','Ol_Chiki','Adlam'];
const languageScriptTerminator=new RegExp(languageScripts.map(s=>String.raw`\p{Script=${s}}`).join('|'),'u');
// Marks the zh dictionaries already end on, kept as an explicit short-circuit in
// front of the script test: all twelve are Script=Common and therefore already
// accepted by it, so this list changes no verdict today — it anchors the 42
// in-use endings against a future Unicode reclassification and is the documented
// escape hatch for a unit symbol the script test would misjudge (see Å above).
const neutralFinal=new Set(['·','…','→','←','“','”','‘','’','–','—','・','×']);
// Half-width sentence terminators that may never close a Chinese sentence.
// Corpus audit over all 2075 zh-CN/zh-TW values (2026-11-13): no value ends on
// ASCII `.`, `!`, `?`, `;` or `:`, so widening the previous `[.!?]` set to add the
// two characters that used to pass silently (`是否确认;`, `注意:`) rejects no existing
// copy. `,`, `)` and `"` were audited too and also measured 0 hits, but stay out of
// the rule on purpose: closing an inline annotation with a half-width paren or
// quote (`温度(0-2)`) is a plausible legitimate ending, and a check that can veto
// real copy is worse than the gap it closes. The full-width forms are the ones
// the dictionaries actually use as endings (`：` closes 12 zh values, `）` 51), and
// they stay accepted — they fall in the CJK ranges `cjkTerminator` accepts.
const halfWidthTerminator=/[.!?:;]/;
const dictionaries=languages.map(lang=>JSON.parse(fs.readFileSync(`src/i18n/locales/${lang}.json`,'utf8')));
const placeholders=value=>JSON.stringify([...value.matchAll(/{{\s*(\w+)\s*}}/g)].map(m=>m[1]).sort());
for(const [index,dict] of dictionaries.entries()) {
  if(JSON.stringify(Object.keys(dict).sort())!==JSON.stringify(Object.keys(dictionaries[0]).sort()))throw Error(`Key mismatch: ${languages[index]}`);
  for(const [key,value] of Object.entries(dict))if(placeholders(key)!==placeholders(value))throw Error(`Placeholder mismatch: ${languages[index]} ${key}`);
  for(const [key,value] of Object.entries(dict))if(!value.trim())throw Error(`Empty translation: ${languages[index]} ${key}`);
  if(languages[index]==='hi')for(const [key,value] of Object.entries(dict))if(/[\u3400-\u9fff]/.test(value))throw Error(`Untranslated Chinese in Hindi: ${key}`);
  // Mirror of that rule for the Chinese locales: `hi` legitimately ends its
  // sentences with U+0964, and neither the key/placeholder/empty checks nor the
  // source scan can tell a Chinese value from a mis-terminated one.
  if(languages[index].startsWith('zh'))for(const [key,value] of Object.entries(dict)){
    if(devanagari.test(value))throw Error(`Devanagari in Chinese copy: ${languages[index]} ${key}`);
    const final=[...value.trimEnd()].pop();
    // The two guards in front of the script test still carry weight: printable
    // ASCII is exempt wholesale (the dictionaries end 256 zh values on `Agent`,
    // `JSON`, `.csv`, `ms`), and `cjkTerminator` exempts the full-width block,
    // whose full-width Latin forms (`Ａ`, U+FF21) are Script=Latin.
    if(final&&!/[ -~]/.test(final)&&!cjkTerminator.test(final)&&!neutralFinal.has(final)&&languageScriptTerminator.test(final))throw Error(`Non-Chinese sentence terminator: ${languages[index]} ${key} (${final})`);
    if(halfWidthTerminator.test(final)&&/[\u4e00-\u9fff]/.test(value))throw Error(`Half-width sentence terminator in Chinese copy: ${languages[index]} ${key} (${final})`);
  }
}
function scan(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
 const file=path.join(dir,entry.name);if(entry.isDirectory()){scan(file);continue;}if(!/\.tsx?$/.test(file))continue;
 const source=ts.createSourceFile(file,fs.readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true);
 function visit(node){if(ts.isCallExpression(node)&&node.expression.getText(source)==='t'&&node.arguments[0]&&ts.isStringLiteral(node.arguments[0])){
  const key=node.arguments[0].text;if(!(key in dictionaries[0]))throw Error(`Missing translation: ${file}: ${key}`);
 }ts.forEachChild(node,visit);}visit(source);
}}
scan('src');console.log(`Verified ${Object.keys(dictionaries[0]).length} translations in ${languages.join(', ')}`);
