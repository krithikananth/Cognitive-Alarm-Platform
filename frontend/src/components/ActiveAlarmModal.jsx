/**
 * ActiveAlarmModal — fullscreen alarm modal with:
 *   - Multi-step challenge flow (Step X of Y progress bar)
 *   - Countdown timer with visual indicator
 *   - Shake animation on wrong answer
 *   - Anti-snooze: button disabled at limit; difficulty escalates per snooze
 *   - Per-attempt time tracking
 */
import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HiOutlineBellAlert, HiOutlineClock, HiOutlineCheckCircle } from 'react-icons/hi2';
import toast from 'react-hot-toast';
import useActiveAlarmStore from '../store/activeAlarmStore';

/** How long (ms) the memory sequence stays visible, by difficulty. */
const MEMORY_DISPLAY_MS = {
  beginner: 5000,
  easy: 5000,
  medium: 4000,
  hard: 3000,
  expert: 2500,
};

export default function ActiveAlarmModal() {
  const {
    isRinging, challenge, isLoading, error,
    verifyAndDismiss, snoozeAlarm, failWake,
    currentStep, totalSteps,
    canSnooze, snoozeCount, snoozeLimit, snoozeIntervalMinutes,
    escalationLevel,
    timeLeft, failedAttempts,
  } = useActiveAlarmStore();

  const [answer, setAnswer] = useState('');
  const [shaking, setShaking] = useState(false);
  // Memory challenge: show sequence first, then hide and allow input
  const [memoryReady, setMemoryReady] = useState(false);
  const [memorySecondsLeft, setMemorySecondsLeft] = useState(0);

  // ── Audio alarm beep ──
  useEffect(() => {
    let oscillator;
    let audioCtx;
    let intervalId;

    if (isRinging) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();

      const playBeep = () => {
        oscillator = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();
        oscillator.type = 'square';
        oscillator.frequency.setValueAtTime(800, audioCtx.currentTime);
        gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.5);
        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        oscillator.start();
        oscillator.stop(audioCtx.currentTime + 0.5);
      };

      playBeep();
      intervalId = setInterval(playBeep, 1000);
      document.body.style.overflow = 'hidden';
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
      if (audioCtx) audioCtx.close();
      document.body.style.overflow = 'auto';
    };
  }, [isRinging]);

  // ── Shake on error ──
  useEffect(() => {
    if (error) {
      toast.error(error);
      setAnswer('');
      setShaking(true);
      setTimeout(() => setShaking(false), 600);
    }
  }, [error]);

  // ── Memory challenge: memorize phase then hide sequence ──
  useEffect(() => {
    if (!isRinging || !challenge || challenge.type !== 'MEMORY') {
      setMemoryReady(true);
      setMemorySecondsLeft(0);
      return undefined;
    }

    const displayMs =
      MEMORY_DISPLAY_MS[challenge.difficulty] ?? MEMORY_DISPLAY_MS.medium;
    const totalSeconds = Math.ceil(displayMs / 1000);

    setMemoryReady(false);
    setMemorySecondsLeft(totalSeconds);
    setAnswer('');

    const hideTimer = setTimeout(() => {
      setMemoryReady(true);
      setMemorySecondsLeft(0);
    }, displayMs);

    const countdownInterval = setInterval(() => {
      setMemorySecondsLeft((prev) => (prev > 1 ? prev - 1 : 0));
    }, 1000);

    return () => {
      clearTimeout(hideTimer);
      clearInterval(countdownInterval);
    };
  }, [isRinging, challenge?.type, challenge?.prompt, challenge?.difficulty, currentStep]);

  if (!isRinging) {
    return null;
  }

  const isMemoryChallenge = challenge?.type === 'MEMORY';
  const showMemorySequence = isMemoryChallenge && !memoryReady;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!answer.trim() || isLoading) return;
    if (isMemoryChallenge && !memoryReady) return;
    const timeLimit = challenge?.time_limit_seconds || 30;
    const elapsed = Math.max(0, timeLimit - (timeLeft ?? timeLimit));
    const result = await verifyAndDismiss(answer, elapsed, failedAttempts);
    if (result?.dismissed) {
      const wake = result.wakefulness;
      const wakeMsg = wake?.level
        ? ` Wakefulness: ${wake.level} (${wake.score}).`
        : '';
      toast.success((result.message || 'Alarm dismissed!') + wakeMsg);
    } else if (result?.success && !result?.dismissed) {
      toast.success(result.message || `Step ${result.step - 1} correct!`);
      setAnswer('');
    }
  };

  const handleOptionClick = async (opt) => {
    if (isLoading) return;
    const timeLimit = challenge?.time_limit_seconds || 30;
    const elapsed = Math.max(0, timeLimit - (timeLeft ?? timeLimit));
    const result = await verifyAndDismiss(opt, elapsed, failedAttempts);
    if (result?.dismissed) {
      const wake = result.wakefulness;
      const wakeMsg = wake?.level
        ? ` Wakefulness: ${wake.level} (${wake.score}).`
        : '';
      toast.success((result.message || 'Alarm dismissed!') + wakeMsg);
    } else if (result?.success && !result?.dismissed) {
      toast.success(result.message || `Step ${result.step - 1} correct!`);
    }
  };

  const handleSnooze = async () => {
    if (!canSnooze) {
      toast.error(
        snoozeLimit === 0
          ? 'Anti-snooze is on — solve the challenge to dismiss.'
          : 'Snooze limit reached! Solve the challenge.'
      );
      return;
    }
    const res = await snoozeAlarm();
    if (res.success) {
      const mins = res.intervalMinutes || snoozeIntervalMinutes || 5;
      toast.success(
        `Snoozed ${mins} min — next challenge will be harder (escalation ${res.escalationLevel}).`
      );
    }
  };

  const handleGiveUp = async () => {
    if (isLoading) return;
    const confirmed = window.confirm(
      'Give up on this wake cycle? This counts as a failed wake and increases your Failure streak.'
    );
    if (!confirmed) return;
    const res = await failWake();
    if (res?.success) {
      const streak = res.failure_streak ?? 0;
      toast.error(
        res.message || `Wake abandoned. Failure streak: ${streak}.`
      );
    }
  };

  // ── Timer color logic (relative to challenge time limit) ──
  const maxTime = challenge?.time_limit_seconds || 30;
  const timerProgress = Math.max(0, (timeLeft / maxTime) * 100);
  const timerColor =
    timeLeft > maxTime * 0.5 ? 'text-emerald-400' :
    timeLeft > maxTime * 0.2 ? 'text-amber-400' : 'text-red-400';
  const timerBgColor =
    timeLeft > maxTime * 0.5 ? 'bg-emerald-500/20' :
    timeLeft > maxTime * 0.2 ? 'bg-amber-500/20' : 'bg-red-500/20';
  const timerBarColor =
    timeLeft > maxTime * 0.5 ? 'bg-emerald-500' :
    timeLeft > maxTime * 0.2 ? 'bg-amber-500' : 'bg-red-500';

  const snoozeBlockedMessage =
    snoozeLimit === 0
      ? 'Anti-snooze enabled — no snoozing. Solve the challenge.'
      : `Snooze limit reached (${snoozeLimit}/${snoozeLimit}) — solve the challenge!`;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/90 backdrop-blur-md">
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{
            scale: 1,
            opacity: 1,
            x: shaking ? [0, -10, 10, -10, 10, -5, 5, 0] : 0,
          }}
          exit={{ scale: 0.9, opacity: 0 }}
          transition={shaking ? { duration: 0.5 } : undefined}
          className="w-full max-w-lg bg-slate-900 border border-slate-700 rounded-3xl p-8 shadow-2xl relative overflow-hidden"
        >
          {/* Animated background rings */}
          <div
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-accent-500/20 rounded-full blur-3xl animate-ping"
            style={{ animationDuration: '2s' }}
          />

          <div className="relative z-10 flex flex-col items-center text-center">
            {/* ── Bell icon ── */}
            <div className="w-20 h-20 bg-accent-500/20 rounded-2xl flex items-center justify-center mb-4 text-accent-400 animate-bounce">
              <HiOutlineBellAlert className="w-10 h-10" />
            </div>

            <h2 className="text-3xl font-display font-bold text-white mb-1">WAKE UP!</h2>
            <p className="text-slate-400 mb-4">Solve the challenge to turn off the alarm.</p>

            {/* ── Anti-snooze escalation banner ── */}
            {escalationLevel > 0 && (
              <div className="w-full mb-4 px-3 py-2 rounded-xl bg-orange-500/15 border border-orange-500/30 text-orange-300 text-xs font-medium">
                Anti-snooze active — difficulty raised {escalationLevel} level
                {escalationLevel > 1 ? 's' : ''} after snooze
                {escalationLevel > 1 ? 's' : ''}
              </div>
            )}

            {/* ── Multi-step progress bar ── */}
            {totalSteps > 1 && (
              <div className="w-full mb-6">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-accent-400 tracking-widest uppercase">
                    Challenge {currentStep} of {totalSteps}
                  </span>
                  <span className="text-xs text-slate-500">
                    {currentStep - 1} / {totalSteps} solved
                  </span>
                </div>
                <div className="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden">
                  <motion.div
                    className="h-full bg-gradient-to-r from-accent-500 to-primary-500 rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${((currentStep - 1) / totalSteps) * 100}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </div>
                {/* Step dots */}
                <div className="flex justify-between mt-2 px-1">
                  {Array.from({ length: totalSteps }, (_, i) => (
                    <div key={i} className="flex flex-col items-center">
                      {i < currentStep - 1 ? (
                        <HiOutlineCheckCircle className="w-4 h-4 text-emerald-400" />
                      ) : i === currentStep - 1 ? (
                        <div className="w-4 h-4 rounded-full border-2 border-accent-400 bg-accent-500/30 animate-pulse" />
                      ) : (
                        <div className="w-4 h-4 rounded-full border-2 border-slate-600" />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Countdown Timer ── */}
            <div className={`flex items-center gap-2 px-4 py-2 rounded-xl ${timerBgColor} mb-5`}>
              <HiOutlineClock className={`w-5 h-5 ${timerColor}`} />
              <span className={`text-lg font-bold font-mono ${timerColor}`}>
                {Math.floor(timeLeft / 60)}:{String(timeLeft % 60).padStart(2, '0')}
              </span>
              <span className="text-xs text-slate-500 ml-1">/ {maxTime}s</span>
            </div>
            {/* Timer progress bar */}
            <div className="w-full bg-slate-800 rounded-full h-1.5 mb-6 overflow-hidden">
              <motion.div
                className={`h-full rounded-full ${timerBarColor}`}
                animate={{ width: `${timerProgress}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>

            {!challenge ? (
              <div className="w-10 h-10 border-4 border-accent-500 border-t-transparent rounded-full animate-spin my-8" />
            ) : (
              <div className="w-full">
                {/* ── Challenge card ── */}
                <div className="bg-slate-800/50 rounded-2xl p-6 mb-6 border border-slate-700/50">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold tracking-widest text-accent-400 uppercase">
                      {(
                        { WORD_GAME: 'WORD', QUIZ: 'QUIZ', LOGIC: 'LOGIC' }[challenge.type]
                        || challenge.type
                      )} CHALLENGE
                    </span>
                    {challenge.difficulty && (
                      <span className={`text-xs font-bold tracking-widest uppercase px-2 py-0.5 rounded-full ${
                        challenge.difficulty === 'beginner' ? 'bg-emerald-500/20 text-emerald-400' :
                        challenge.difficulty === 'easy' ? 'bg-teal-500/20 text-teal-400' :
                        challenge.difficulty === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                        challenge.difficulty === 'hard' ? 'bg-orange-500/20 text-orange-400' :
                        'bg-red-500/20 text-red-400'
                      }`}>
                        {challenge.difficulty}
                        {escalationLevel > 0 ? ' ↑' : ''}
                      </span>
                    )}
                  </div>

                  {isMemoryChallenge ? (
                    <div className="my-6">
                      {showMemorySequence ? (
                        <>
                          <p className="text-sm text-accent-400 font-medium mb-3">
                            Memorize this sequence…
                          </p>
                          <div
                            className="text-4xl font-bold tracking-[1em] text-white select-none"
                            onCopy={(e) => e.preventDefault()}
                            onContextMenu={(e) => e.preventDefault()}
                          >
                            {challenge.prompt}
                          </div>
                          <p className="text-xs text-slate-500 mt-3">
                            Hides in {memorySecondsLeft}s
                          </p>
                        </>
                      ) : (
                        <>
                          <p className="text-sm text-slate-400 font-medium mb-3">
                            Enter the sequence from memory
                          </p>
                          <div className="text-4xl font-bold tracking-[0.5em] text-slate-600 select-none">
                            {'•'.repeat(Math.min(challenge.prompt?.length || 4, 12))}
                          </div>
                        </>
                      )}
                    </div>
                  ) : (
                    <div className="text-2xl font-bold text-white my-4">
                      {challenge.prompt}
                    </div>
                  )}
                </div>

                {/* ── Options or text input ── */}
                {challenge.options ? (
                  <div className="grid grid-cols-2 gap-4 mb-6">
                    {challenge.options.map((opt, i) => (
                      <button
                        key={i}
                        onClick={() => handleOptionClick(opt)}
                        disabled={isLoading}
                        className="btn-secondary h-16 text-xl font-bold bg-slate-800 hover:bg-slate-700 border-slate-600 hover:border-slate-500 transition-all active:scale-95"
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                ) : showMemorySequence ? (
                  <div className="mb-6 px-4 py-6 rounded-2xl border border-dashed border-slate-600 bg-slate-800/30">
                    <p className="text-slate-500 text-sm">
                      Answer input unlocks after the sequence is hidden.
                    </p>
                  </div>
                ) : (
                  <form onSubmit={handleSubmit} className="mb-6">
                    <input
                      type="text"
                      value={answer}
                      onChange={(e) => setAnswer(e.target.value)}
                      placeholder={
                        isMemoryChallenge
                          ? 'Type the sequence from memory...'
                          : 'Type your answer here...'
                      }
                      className="input w-full text-center text-xl h-14 mb-4"
                      autoFocus
                      disabled={isLoading}
                    />
                    <button
                      type="submit"
                      disabled={isLoading || !answer.trim()}
                      aria-disabled={isLoading || !answer.trim()}
                      className="btn-primary w-full h-14 text-lg font-bold"
                    >
                      {isLoading ? 'Verifying...' : 'Submit Answer'}
                    </button>
                  </form>
                )}

                {/* ── Failed attempts indicator ── */}
                {failedAttempts > 0 && (
                  <p className="text-red-400 text-sm mb-4">
                    {failedAttempts} failed attempt{failedAttempts > 1 ? 's' : ''}
                  </p>
                )}

                {/* ── Snooze / anti-snooze control ── */}
                {canSnooze ? (
                  <button
                    onClick={handleSnooze}
                    disabled={isLoading}
                    className="text-slate-500 hover:text-white underline decoration-slate-600 hover:decoration-white underline-offset-4 transition text-sm font-medium"
                  >
                    Snooze ({snoozeCount}/{snoozeLimit} used) — harder next time
                  </button>
                ) : (
                  <p className="text-red-400/80 text-xs font-medium">
                    {snoozeBlockedMessage}
                  </p>
                )}

                {/* Final failed wake — not a mid-cycle wrong answer */}
                <button
                  type="button"
                  onClick={handleGiveUp}
                  disabled={isLoading}
                  className="mt-4 text-red-400/70 hover:text-red-300 text-xs font-medium underline decoration-red-500/30 hover:decoration-red-400 underline-offset-4 transition"
                >
                  Give up this wake
                </button>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
