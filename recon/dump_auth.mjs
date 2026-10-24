// Dump the Yoto tab's storage + cookies to find the long-lived auth material.
import { connect } from './cdp.mjs';

const cdp = await connect('my.yotoplay.com');

const ls = await cdp.send('Runtime.evaluate', {
  expression: `JSON.stringify({
    localStorage: Object.fromEntries(Object.entries(localStorage)),
    sessionStorage: Object.fromEntries(Object.entries(sessionStorage)),
  }, (k,v)=> typeof v === 'string' && v.length > 400 ? v.slice(0,400)+'...[len '+v.length+']' : v, 2)`,
  returnByValue: true,
});
console.log('=== STORAGE ===');
console.log(ls.result.value);

const cookies = await cdp.send('Network.getCookies', { urls: ['https://my.yotoplay.com/', 'https://login.yotoplay.com/'] });
console.log('\n=== COOKIES (names + length only) ===');
for (const c of cookies.cookies) {
  console.log(`${c.domain.padEnd(28)} ${c.name.padEnd(30)} len=${String(c.value.length).padStart(5)} httpOnly=${c.httpOnly} sameSite=${c.sameSite} expires=${c.expires}`);
  if (/txs|refresh|token/i.test(c.name)) {
    console.log(`    VALUE: ${c.value.slice(0, 300)}`);
  }
}

cdp.close();
process.exit(0);
