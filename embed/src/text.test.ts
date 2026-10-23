import assert from "node:assert/strict";
import { test } from "node:test";
import { explainConnectError, explainProviderError, isHangUp, isLocal, isSeriousError, lastSentences } from "./text.ts";

test("hang-up commands match exactly", () => {
  for (const t of ["End the call.", "please hang up", "Disconnect", "ok stop this call!"]) assert.ok(isHangUp(t), t);
  for (const t of ["How do you end the call?", "don't hang up", "disconnected"]) assert.ok(!isHangUp(t), t);
});

test("local URLs", () => {
  assert.ok(isLocal("http://localhost:7860/x"));
  assert.ok(isLocal("http://127.0.0.1"));
  assert.ok(!isLocal("http://localhost.evil.example"));
  assert.ok(!isLocal("https://example.com"));
});

test("captions keep the last sentences", () => {
  assert.equal(lastSentences("One. Two! Three? Four."), "Three? Four.");
  assert.equal(lastSentences("no punctuation"), "no punctuation");
});

test("errors are explained in plain language", () => {
  assert.match(explainProviderError("Error code: 404 model_not_found").title, /model/);
  assert.match(explainProviderError("invalid_api_key").title, /key/);
  assert.match(explainProviderError("weird").title, /Couldn't/);
  assert.match(explainConnectError("Request failed 503").title, /busy/);
  assert.match(explainConnectError("status 429").title, /Too many/);
  assert.match(explainConnectError("NotAllowedError").title, /Microphone/);
  assert.ok(isSeriousError("invalid model", false));
  assert.ok(!isSeriousError("TTS timing drift", false));
  assert.ok(isSeriousError("", true));
});
