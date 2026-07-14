# Wave 2 — Port Completion: 0 Violations Achieved

**Date**: 2026-07-07
**Branch**: `feature/wave-2-port-completion`
**Status**: ✅ Complete

## Summary

Wave 2 completes the Port extraction work started in Wave 1.5, driving ArchUnit react→harness violations from **178 → 0** (production code) and eliminating all 5 ArchUnit rule violations to **0 across the board**.

## Violation Trajectory

| Phase | Violations | Delta | Key Change |
|-------|-----------|-------|------------|
| Wave 1.5 end | 329 | — | Baseline after initial Port extraction |
| Wave 2 P0 | 178 | -151 | ChatRunContext unification + value object migration |
| Wave 2 P1 | 148 | -30 | ProviderTraceCollectorPort |
| Wave 2 P2 | 121 | -27 | L0JournalPort + L0TurnDraft migration |
| Wave 2 P3 | 108 | -13 | TodoSessionTracker migration |
| Wave 2 P4 | 83 | -25 | HarnessRuntimePort (10 methods) |
| Wave 2 P5 | 13 | -70 | 9 Port interfaces + TokenJuiceApplyResult migration |
| Wave 2 P6 | 6 | -7 | ConstrainedDecodingPort + PreValidation |
| Wave 2 P7 | 0 | -6 | Test-only fixes + PreReasoningHook migration |

## Port Interfaces Created (15 total)

### contracts/runtime/ — New Ports

| Port | Methods | Harness Impl | Notes |
|------|---------|-------------|-------|
| `ProviderTraceCollectorPort` | 3 | `ProviderTraceCollector` | Trace recording for tool calls/responses |
| `L0JournalPort` | 5 | `AgentExecutionContext` | L0 turn-draft journal staging |
| `HarnessRuntimePort` | 10 | `HarnessRuntime` | Runtime checks (stagnation, unknown tool, etc.) |
| `LlmResiliencePort` | 3 | `LlmCircuitBreaker` | Circuit breaker allow/record |
| `LlmRateLimitPort` | 1 | `LlmRateLimiter` | Rate limit tryAcquire |
| `ModelRouterPort` | 3 | `ModelRouter` | Route/upgrade/thinkingExtraBody |
| `TokenSaverPort` | 2 | `TokenSaver` | Needs upgrade checks |
| `TokenJuicePort` | 1 | `TokenJuice` | Apply token juice to messages |
| `RoutingMetricsPort` | 1 | `RoutingMetrics` | Record route decisions |
| `UsageTrackerPort` | 1 | `UsageTracker` | Record usage metrics |
| `DelegationCancelPort` | 1 | `DelegationCancelRegistry` | Delegation cancel check |
| `ConstrainedDecodingPort` | 1 + record | `ConstrainedDecodingAdapter` | Pre-validation with adapter pattern |
| `PreReasoningHook` | 1 | (5 impls in react/ + context/) | Moved from react/ to contracts/ |

### contracts/runtime/ — Value Objects Migrated

| Value Object | Source | Destination |
|-------------|--------|-------------|
| `L0TurnDraft` | `memory/` | `contracts/runtime/` |
| `TodoSessionTracker` | `react/` | `contracts/runtime/` |
| `TokenJuiceApplyResult` | `harness/` | `contracts/runtime/` |
| `CompactSummary` | (already in contracts/) | — |

## Design Decisions

### D1: ConstrainedDecodingAdapter (Adapter Pattern)

`ConstrainedDecodingLayer` is a utility class with static methods and a static `AtomicInteger` counter. It cannot directly implement an interface. Solution: `ConstrainedDecodingAdapter` is a Spring `@Component` that delegates to the static methods and maps between the layer's `PreValidation` record and the port's `PreValidation` record.

**Why**: Static utility classes are common in the codebase; the adapter pattern preserves existing code while enabling interface-based dependency injection.

### D2: ModelRouter.thinkingExtraBody — Static → Instance

`ModelRouter.thinkingExtraBody()` was a static method called from 4 locations. Changed to instance method with `@Override` on `ModelRouterPort`. All callers updated to use injected `ModelRouterPort`.

**Why**: Interface methods must be instance methods. The static→instance conversion is safe because `ModelRouter` is a Spring singleton.

### D3: PreReasoningHook Migration to contracts/

`PreReasoningHook` was in `react/` but implemented by `context/ContextPackRecorder`, creating a context→react dependency violation. Moved the interface to `contracts/runtime/` so both `react/` and `context/` depend on `contracts/` instead.

**Why**: Functional interfaces that cross package boundaries belong in contracts/. This is consistent with the Port-first dependency direction: leaf packages depend on contracts/, never on each other.

### D4: StubChatRunContext for Test Isolation

Created `StubChatRunContext` in test sources to replace `AgentExecutionContext` in test setup/teardown. Tests bind it via `ToolExecutionContexts.bind()` instead of `AgentExecutionContext.set()`.

**Why**: Test code in `react/` that imports `harness/AgentExecutionContext` violates ArchUnit rules. The stub provides the same ThreadLocal behavior through the contracts/ API.

## ArchUnit Final State

All **6** rules pass with **0 violations**:

1. **boundary/ → react/ or harness/**: 0 violations
2. **context/ → react/ or harness/**: 0 violations
3. **memory/ → react/ or harness/**: 0 violations
4. **react/ → harness/**: 0 violations (was 371 at Wave 0.5)
5. **service/ → react/**: 0 violations
6. **loop/ → react/ or harness/**: 0 violations (strict, <br>ReActTurnEngine is in react/ not loop/)

## Test Results

- SDK tests: **209/209** passing
- ArchUnit: **6/6** rules passing (all 0 violations)
- Full reactor: compiles clean
- dev-assembler: **112** tests passing (MigrationParityTest + 81 + 30)

## Files Changed (Key)

### contracts/ (New)
- `ContextTrimmingPort.java`, `CompactSummary.java` (Wave 1.5)
- `ProviderTraceCollectorPort.java`
- `L0JournalPort.java`, `L0TurnDraft.java`
- `TodoSessionTracker.java`
- `HarnessRuntimePort.java`
- `LlmResiliencePort.java`, `LlmRateLimitPort.java`
- `ModelRouterPort.java`
- `TokenSaverPort.java`, `TokenJuicePort.java`, `TokenJuiceApplyResult.java`
- `RoutingMetricsPort.java`, `UsageTrackerPort.java`
- `DelegationCancelPort.java`
- `ConstrainedDecodingPort.java` (with nested `PreValidation`)
- `PreReasoningHook.java` (moved from react/)

### harness/ (Implements Ports)
- `AgentExecutionContext` → implements `ChatRunContext`, `L0JournalPort`
- `HarnessRuntime` → implements `HarnessRuntimePort`
- `ConstrainedDecodingAdapter` (NEW) → implements `ConstrainedDecodingPort`
- `ModelRouter` → implements `ModelRouterPort` (static→instance for thinkingExtraBody)
- `LlmCircuitBreaker` → implements `LlmResiliencePort`
- `LlmRateLimiter` → implements `LlmRateLimitPort`
- `TokenSaver` → implements `TokenSaverPort`
- `TokenJuice` → implements `TokenJuicePort`
- `RoutingMetrics` → implements `RoutingMetricsPort`
- `UsageTracker` → implements `UsageTrackerPort`
- `DelegationCancelRegistry` → implements `DelegationCancelPort`

### react/ (Port type conversions)
- `ReActLoop.java`, `ReActTurnLoop.java`, `ReActTurnLifecycle.java`
- `ReActToolActPhase.java`, `ReActCompletionGate.java`
- `ReActLlmInvoker.java`, `ReActTurnPreamble.java`
- `ContextTrimmingHook.java`, `SessionMemoryRecorder.java`
- `ReActChatOptionsFactory.java`, `ReActModelFallback.java`
- `ActiveRunRegistry.java`, `ReActContextHelpers.java`
- All 4 `PreReasoningHook` implementations (import changed)

### Deleted
- `react/PreReasoningHook.java` (moved to contracts/)
- `memory/L0TurnDraft.java` (moved to contracts/)
- `react/TodoSessionTracker.java` (moved to contracts/)
- `harness/TokenJuiceApplyResult.java` (moved to contracts/)

### Test
- `StubChatRunContext.java` (NEW) — test stub replacing AgentExecutionContext
- `SteeringSuppliersTest.java` — uses StubChatRunContext + ToolExecutionContexts
- `PhasedAgentLoopExecuteTest.java` — ToolExecutionContexts.clear()
- `ReActTurnPreambleTest.java` — ToolExecutionContexts.clear()
- `ReActLoopDeferCompletionTest.java` — Port type mocks
- `SdkArchitectureTest.java` — re-freeze baseline

## Extended Waves (2.5–2.15)

After the core Port extraction achieved 0 violations in production code, the work extended across services to eliminate all react/ and harness/ imports.

### Wave 2.5 — agent-service AgentExecutionContext 解耦
- 17 agent-service files: AgentExecutionContext → ChatRunContext (0 harness/AgentExecutionContext imports in agent-service/src/main/)
- SseEmitterManager + ExecutionTraceLog: AgentExecutionContext → ChatRunContext, ActiveRunRegistry → ChatActiveRunPort
- WebConfirmationHandler: LLMConfigManager → LlmConfigPort
- ChatRunContext +14 methods, ChatActiveRunPort +3 methods

### Wave 2.7 — ReActTurnEngine + Hook chain contract
- ReActTurnEngine in `loop/` implements TurnRunner, wraps ReActLoop.execute()
- ArchUnit rule 4 relaxed: only ReActTurnEngine bridges to react/
- HookChainOrderInvariantsTest: 5 tests verifying F2 contract (4 pre + 4 post + 1 postTurn hooks)
- SDK tests 203 → 208 (+5), ArchUnit 6 rules 0 violations, 9 E2E pass

### Wave 2.8 — agent-service harness/ Port 收敛 (49 → 5)
- 8 pure-JDK value objects migrated to contracts/
- 4 Ports expanded: LlmConfigPort, RunObservabilityPort, DelegationCancelPort
- New RunEventQueryPort (read-side split from RunObservabilityPort)
- 44 of 49 harness imports eliminated (−89%)

### Wave 2.9–2.10 — agent-service harness/ 完全解耦 (5 → 0)
- 3 new Ports: ProactiveTickerPort, DelegationDeliverablePort, WorkerAgentPort
- WorkerAgentFactoryPort + SDK WorkerAgentFactory bean
- WorkerAgent construction fully encapsulated in SDK

### Wave 2.11 — react/ 工具类迁 contracts/
- CoordinatorToolPolicy package fix (was in contracts/ but package said react/)
- AgentToolCallbacks.concat → contracts/runtime/AgentToolCallbacks
- RiskAwareToolCallback.wrap() static factory
- react/AgentToolCallbackUtils deleted; react/ imports 13 → 11

### Wave 2.12+2.13 — agent-service react/ 完全解耦 (11 → 0)
- ChatConcurrencyPort +4 methods (pollSteering/cancel/clear/isSessionBusy)
- 4 new Ports: ReActLoopPort (5 execute() overloads), FollowUpContinuationLoopPort, NoReplyGatePort, SteeringSuppliers (relocated to contracts/runtime/)
- agent-service depends only on contracts/ Ports + SDK boundary/ + tools/team classes

### Wave 2.14 — obs-service harness/ 完全解耦 (2 → 0)
- RunEventQueryPort +8 methods
- DecisionPage record → contracts/diagnostics/
- **MAJOR MILESTONE**: All 4 services (agent-service, platform-service, bus-service, observability-service) + dev-assembler main: 0 react/ + 0 harness/ production imports

### Wave 2.15 — Test Port migration (10 batches, 16 files)
- ProviderTraceCollector → ProviderTraceCollectorPort (4 files)
- AgentRunEventService → RunObservabilityPort (4 files)
- MessageQueue → ChatConcurrencyPort (3 files)
- LLMConfigManager → LlmConfigPort (3 files)
- ReActLoop → ReActLoopPort, ReActSseNotifier → SseNotifierPort, TokenJuice → TokenJuicePort, HarnessRuntime → HarnessRuntimePort
- ~111 test imports remaining: 48 legitimate (concrete class tests), 23 AgentExecutionContext (Wave 3), 6 no Port

### Wave 3 preview — @Deprecated marking
- PhasedAgentLoop / FollowUpContinuationLoop / SteeringSuppliers / EvidenceGate / PhaseToolWhitelist / PhaseHandoffService all marked @Deprecated(since="2.0", forRemoval=true)
- CUTOVER Wave 3 step 5 completed early

## Next Steps

Wave 2 Port completion is done. The split goal of one-way dependency boundaries (contracts ← SDK ← services) is structurally complete for production source code.

- **Wave 3**: SessionLoopDispatcher design + production wiring (cut over from ReActLoop to SessionLoop)
- **Wave 3 (test cleanup)**: Address remaining ~111 test imports, ~23 AgentExecutionContext fat-class uses
- **Wave 4**: Physical deletion of 1.0 dual-loop code (MessageQueue, FollowUpContinuationLoop, SteeringSuppliers)
