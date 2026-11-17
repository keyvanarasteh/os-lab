/**
 * Policy-Driven Frida Native Interceptor & Argument/Return-Value Tampering Library (PENT-07)
 *
 * Traces and tampers native function arguments in `onEnter` and return values via
 * `onLeave` / `retval.replace(...)` driven by a structured JSON policy.
 *
 * Scope Guard (Authorization-Only / Lab-Only):
 *   Permitted ONLY against the isolated lab auth harness (`hedef.c` / `hedef` / `hedef.exe`)
 *   and its authorized functions (`parola_kontrol`, `check_password`). Out-of-scope targets
 *   and functions are refused before any `Interceptor.attach` call occurs.
 *
 * How to load:
 *   1. Live Frida CLI (attach or spawn compiled `hedef`):
 *        frida -n hedef -l android-lab/lab/hooks/tamper_policy.js
 *   2. Python RPC / Deterministic Golden Runner (`tamper_runner.py`):
 *        python3 android-lab/lab/scripts/tamper_runner.py \
 *          --policy android-lab/lab/tests/fixtures/pent07/policies/04_onleave_retval_replace.json
 */

"use strict";

var ALLOWED_TARGETS = ["hedef", "hedef.exe", "hedef.c"];
var ALLOWED_FUNCTIONS = ["parola_kontrol", "check_password"];

var _attachedHooks = [];
var _recordedEvents = [];

function getDefaultPolicy() {
    return {
        version: 1,
        policy_id: "default-retval-replace",
        description: "Observe parola_kontrol arguments and replace return value 0 with 1",
        target: {
            source: "android-lab/lab/tests/targets/hedef.c",
            function: "parola_kontrol"
        },
        rules: [
            {
                function: "parola_kontrol",
                onEnter: {
                    observe_args: [
                        { index: 0, name: "girilen_parola", type: "utf8" },
                        { index: 1, name: "yetki_seviyesi", type: "int32" }
                    ],
                    tamper_args: []
                },
                onLeave: {
                    observe_retval: true,
                    retval_replace: {
                        enabled: true,
                        when_equals: 0,
                        value: 1,
                        type: "int32"
                    }
                }
            }
        ]
    };
}

function normalizeTargetName(rawName) {
    if (typeof rawName !== "string") {
        return "";
    }
    var parts = rawName.replace(/\\/g, "/").split("/");
    return parts[parts.length - 1].toLowerCase();
}

function assertPolicyScope(policy) {
    if (!policy || typeof policy !== "object") {
        throw new Error("ScopeGuard: policy must be a non-null object.");
    }

    var targetSource = policy.target && policy.target.source ? policy.target.source : "";
    var targetBase = normalizeTargetName(targetSource);
    if (targetBase && ALLOWED_TARGETS.indexOf(targetBase) === -1) {
        throw new Error("ScopeGuard: unauthorized target source: " + targetSource);
    }

    if (typeof Process !== "undefined" && typeof Process.enumerateModules === "function") {
        var mods = Process.enumerateModules();
        if (mods && mods.length > 0) {
            var mainBase = normalizeTargetName(mods[0].name);
            if (ALLOWED_TARGETS.indexOf(mainBase) === -1) {
                throw new Error("ScopeGuard: refusing non-lab host process: " + mods[0].name);
            }
        }
    }

    var rules = Array.isArray(policy.rules) ? policy.rules : [];
    for (var i = 0; i < rules.length; i++) {
        var fn = rules[i].function;
        if (ALLOWED_FUNCTIONS.indexOf(fn) === -1) {
            throw new Error("ScopeGuard: unauthorized hook function: " + String(fn));
        }
    }
}

function resolveSymbol(moduleName, funcName) {
    if (typeof Module !== "undefined" && typeof Module.findExportByName === "function") {
        var exported = Module.findExportByName(moduleName || null, funcName);
        if (exported !== null && !exported.isNull()) {
            return exported;
        }
    }
    if (typeof DebugSymbol !== "undefined" && typeof DebugSymbol.fromName === "function") {
        var sym = DebugSymbol.fromName(funcName);
        if (sym && sym.address && !sym.address.isNull()) {
            return sym.address;
        }
    }
    return null;
}

function readArg(args, spec) {
    var idx = spec.index;
    var kind = spec.type || "pointer";
    if (args[idx] === undefined || args[idx] === null) {
        return null;
    }
    if (kind === "utf8") {
        return args[idx].isNull() ? null : args[idx].readUtf8String();
    }
    if (kind === "int32") {
        return args[idx].toInt32();
    }
    if (kind === "uint32") {
        return args[idx].toUInt32();
    }
    return args[idx].toString();
}

function tamperArg(callCtx, args, rule) {
    var idx = rule.index;
    var kind = rule.type || "int32";
    var current = readArg(args, { index: idx, type: kind });

    if (rule.when_equals !== undefined && current !== rule.when_equals) {
        return null;
    }

    if (kind === "utf8") {
        var buf = Memory.allocUtf8String(String(rule.value));
        if (!Array.isArray(callCtx._allocs)) {
            callCtx._allocs = [];
        }
        // Pin native allocation for the duration of the intercepted call so GC cannot reclaim it.
        callCtx._allocs.push(buf);
        args[idx] = buf;
    } else if (kind === "int32" || kind === "uint32" || kind === "pointer") {
        args[idx] = ptr(rule.value);
    } else {
        throw new Error("Unsupported tamper argument type: " + String(kind));
    }

    return {
        index: idx,
        name: rule.name || ("arg" + idx),
        type: kind,
        before: current,
        after: rule.value
    };
}

function tamperRetval(retval, rule) {
    var original = retval.toInt32();
    if (!rule || !rule.enabled) {
        return {
            original: original,
            replaced: original,
            tampered: false
        };
    }

    if (rule.when_equals !== undefined && original !== rule.when_equals) {
        return {
            original: original,
            replaced: original,
            tampered: false
        };
    }

    var replacement = Number(rule.value);
    retval.replace(ptr(replacement));
    return {
        original: original,
        replaced: replacement,
        tampered: true
    };
}

function emitEvent(event) {
    _recordedEvents.push(event);
    if (typeof send === "function") {
        send({ type: "pent07:event", payload: event });
    }
}

function attachRule(moduleName, rule) {
    var funcName = rule.function;
    var targetAddr = resolveSymbol(moduleName, funcName);
    if (targetAddr === null) {
        throw new Error("Unable to resolve target symbol: " + funcName);
    }

    var onEnterCfg = rule.onEnter || {};
    var onLeaveCfg = rule.onLeave || {};
    var observeArgs = Array.isArray(onEnterCfg.observe_args) ? onEnterCfg.observe_args : [];
    var tamperArgs = Array.isArray(onEnterCfg.tamper_args) ? onEnterCfg.tamper_args : [];

    var listener = Interceptor.attach(targetAddr, {
        onEnter: function (args) {
            this._allocs = [];
            this._func = funcName;
            this._observed = {};
            this._tampered = [];

            for (var i = 0; i < observeArgs.length; i++) {
                var spec = observeArgs[i];
                var key = spec.name || ("arg" + spec.index);
                this._observed[key] = readArg(args, spec);
            }

            for (var j = 0; j < tamperArgs.length; j++) {
                var change = tamperArg(this, args, tamperArgs[j]);
                if (change !== null) {
                    this._tampered.push(change);
                }
            }

            console.log(
                "[INTERCEPTOR] onEnter " + funcName +
                " | observed=" + JSON.stringify(this._observed) +
                " | tampered=" + JSON.stringify(this._tampered)
            );
        },
        onLeave: function (retval) {
            var leaveResult = tamperRetval(retval, onLeaveCfg.retval_replace);
            var event = {
                function: this._func,
                observed_args: this._observed,
                tampered_args: this._tampered,
                original_retval: leaveResult.original,
                final_retval: leaveResult.replaced,
                retval_tampered: leaveResult.tampered
            };

            console.log(
                "[INTERCEPTOR] onLeave " + this._func +
                " | original_retval=" + leaveResult.original +
                " | final_retval=" + leaveResult.replaced +
                " | retval_replaced=" + leaveResult.tampered
            );
            emitEvent(event);
        }
    });

    _attachedHooks.push(listener);
    return {
        function: funcName,
        address: targetAddr.toString()
    };
}

function clearHooks() {
    for (var i = 0; i < _attachedHooks.length; i++) {
        _attachedHooks[i].detach();
    }
    _attachedHooks = [];
}

function applyPolicy(policy) {
    assertPolicyScope(policy);
    clearHooks();
    _recordedEvents = [];

    var moduleName = (policy.target && policy.target.module) ? policy.target.module : null;
    var rules = Array.isArray(policy.rules) ? policy.rules : [];
    var attached = [];

    for (var i = 0; i < rules.length; i++) {
        attached.push(attachRule(moduleName, rules[i]));
    }

    console.log(
        "[INTERCEPTOR] policy=" + String(policy.policy_id || "unnamed") +
        " | attached=" + attached.length
    );

    return {
        policy_id: policy.policy_id || "unnamed",
        attached: attached
    };
}

function getEvents() {
    return _recordedEvents.slice();
}

if (typeof rpc !== "undefined") {
    rpc.exports = {
        applyPolicy: applyPolicy,
        getEvents: getEvents,
        getDefaultPolicy: getDefaultPolicy
    };
}

(function autoStart() {
    var rootObj = typeof globalThis !== "undefined" ? globalThis : null;
    if (rootObj && rootObj.__PENT07_POLICY__) {
        applyPolicy(rootObj.__PENT07_POLICY__);
    } else if (typeof Interceptor !== "undefined" && typeof Process !== "undefined") {
        // Standalone CLI load (`frida -n hedef -l tamper_policy.js`): attach default retval.replace policy.
        try {
            applyPolicy(getDefaultPolicy());
        } catch (err) {
            console.log("[INTERCEPTOR] autoStart skipped: " + err.message);
        }
    }
})();
