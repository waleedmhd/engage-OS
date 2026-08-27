/**
 * One-off reproduction test for the "login page flashes then goes blank" bug.
 *
 * Root cause: middleware treated a stale access_token cookie as authenticated
 * based on presence alone, so an expired-but-present cookie redirected the
 * user off /login forever. isJwtValid must reject expired/malformed tokens.
 *
 * Run: node scripts/jwt.test.mjs
 */
import assert from 'node:assert';
import { isJwtValid } from '../lib/jwt.ts';

function makeToken(expSecondsFromNow) {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    .toString('base64url');
  const payload = Buffer.from(
    JSON.stringify({ sub: 'u1', exp: Math.floor(Date.now() / 1000) + expSecondsFromNow }),
  ).toString('base64url');
  return `${header}.${payload}.sig`;
}

let passed = 0;
function check(name, cond) {
  assert.ok(cond, `FAIL: ${name}`);
  passed += 1;
}

check('valid future token is accepted', isJwtValid(makeToken(600)) === true);
check('expired token is rejected', isJwtValid(makeToken(-60)) === false);
check('missing token is rejected', isJwtValid(undefined) === false);
check('empty token is rejected', isJwtValid('') === false);
check('malformed token is rejected', isJwtValid('not-a-jwt') === false);
check('token without exp is rejected', isJwtValid('eyJ9.eyJ9.s') === false);

console.log(`OK — ${passed} assertions passed`);
