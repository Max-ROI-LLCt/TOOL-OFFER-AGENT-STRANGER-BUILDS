"use strict";

const net = require("node:net");
const http = require("node:http");
const https = require("node:https");
const tls = require("node:tls");

function checkAddress(value) {
  const options = typeof value === "string" || value instanceof URL ? new URL(value) : value || {};
  const host = options.hostname || options.host || "localhost";
  if (!["localhost", "127.0.0.1", "::1", "[::1]"].includes(host)) {
    throw new Error("External network prohibited in local judging tests");
  }
}

for (const module of [http, https]) {
  for (const method of ["request", "get"]) {
    const original = module[method];
    module[method] = function guardedRequest(...parameters) {
      checkAddress(parameters[0]);
      return original.apply(this, parameters);
    };
  }
}

const originalConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function guardedConnect(...parameters) {
  const options = Array.isArray(parameters[0]) ? parameters[0] : parameters;
  checkAddress(typeof options[0] === "object" ? options[0] : {host: typeof options[1] === "string" ? options[1] : "localhost"});
  return originalConnect.apply(this, parameters);
};
const originalTlsConnect = tls.connect;
tls.connect = function guardedTlsConnect(...parameters) {
  checkAddress(typeof parameters[0] === "object" ? parameters[0] : {host: parameters[1]});
  return originalTlsConnect.apply(this, parameters);
};
const originalFetch = globalThis.fetch;
globalThis.fetch = function guardedFetch(input, options) {
  checkAddress(typeof input === "string" || input instanceof URL ? input : input.url);
  return originalFetch(input, options);
};
