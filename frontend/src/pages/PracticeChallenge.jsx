/**
 * PracticeChallenge — train on real cognitive challenges without ringing an
 * alarm. Uses /alarms/challenge/practice (+ /verify); does not affect wake
 * streaks, habit score logs, or dismiss flow.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import {
  HiOutlineArrowLeft,
  HiOutlineCheckCircle,
  HiOutlineClock,
  HiOutlinePuzzlePiece,
  HiOutlineXCircle,
} from 'react-icons/hi2';
import { alarmAPI } from '../services/api';

const CHALLENGE_TYPES = [
  { value: 'random', label: 'Random' },
  { value: 'math', label: 'Math' },
  { value: 'logic', label: 'Logic' },
  { value: 'memory', label: 'Memory' },
  { value: 'word_game', label: 'Word' },
  { value: 'pattern', label: 'Pattern' },
  { value: 'riddle', label: 'Riddle' },
  { value: 'quiz', label: 'Quiz' },
];

const DIFFICULTY_LEVELS = ['beginner', 'easy', 'medium', 'hard', 'expert'];

const MEMORY_DISPLAY_MS = {
  beginner: 5000,
  easy: 5000,
  medium: 4000,
  hard: 3000,
  expert: 2500,
};

const TYPE_LABEL = {
  WORD_GAME: 'WORD',
  QUIZ: 'QUIZ',
  LOGIC: 'LOGIC',
};

export default function PracticeChallenge() {
  const [challengeType, setChallengeType] = useState('random');
  const [difficulty, setDifficulty] = useState('medium');
  const [challenge, setChallenge] = useState(null);
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState(null);
  const [shaking, setShaking] = useState(false);
  const [timeLeft, setTimeLeft] = useState(null);
  const [memoryReady, setMemoryReady] = useState(true);
  const [memorySecondsLeft, setMemorySecondsLeft] = useState(0);
  const [stats, setStats] = useState({ correct: 0, wrong: 0, points: 0 });
  const [lastResult, setLastResult] = useState(null);

  const timerRef = useRef(null);
  const issuedAtRef = useRef(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startTimer = useCallback(
    (limitSeconds) => {
      clearTimer();
      const limit = Math.max(1, Number(limitSeconds) || 30);
      setTimeLeft(limit);
      issuedAtRef.current = Date.now();
      timerRef.current = setInterval(() => {
        setTimeLeft((prev) => {
          if (prev == null) return prev;
          if (prev <= 1) {
            clearTimer();
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    },
    [clearTimer]
  );

  useEffect(() => () => clearTimer(), [clearTimer]);

  // Memory challenge: show sequence, then hide
  useEffect(() => {
    if (!challenge || challenge.type !== 'MEMORY') {
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
  }, [challenge?.type, challenge?.prompt, challenge?.difficulty]);

  const startChallenge = useCallback(async () => {
    setLoading(true);
    setError(null);
    setLastResult(null);
    setAnswer('');
    try {
      const { data } = await alarmAPI.startPractice({
        challenge_type: challengeType,
        difficulty,
      });
      setChallenge(data);
      startTimer(data.time_limit_seconds || 30);
    } catch (err) {
      const detail =
        err?.response?.data?.detail || 'Failed to start practice challenge.';
      setError(typeof detail === 'string' ? detail : 'Failed to start practice challenge.');
      setChallenge(null);
      clearTimer();
    } finally {
      setLoading(false);
    }
  }, [challengeType, difficulty, startTimer, clearTimer]);

  const elapsedSeconds = () => {
    if (!issuedAtRef.current) return 0;
    return Math.max(0, Math.round((Date.now() - issuedAtRef.current) / 1000));
  };

  const submitAnswer = async (value) => {
    const trimmed = String(value ?? '').trim();
    if (!trimmed || verifying || !challenge) return;
    if (challenge.type === 'MEMORY' && !memoryReady) return;

    setVerifying(true);
    setError(null);
    clearTimer();
    try {
      const { data } = await alarmAPI.verifyPractice({
        user_answer: trimmed,
        time_taken_seconds: elapsedSeconds(),
        failed_attempts: 0,
      });

      setLastResult(data);
      setChallenge(null);
      setAnswer('');

      if (data.correct) {
        setStats((s) => ({
          correct: s.correct + 1,
          wrong: s.wrong,
          points: s.points + (data.score?.total_points || 0),
        }));
        toast.success(data.message || 'Correct!');
      } else {
        setStats((s) => ({
          correct: s.correct,
          wrong: s.wrong + 1,
          points: s.points,
        }));
        setShaking(true);
        setTimeout(() => setShaking(false), 500);
        toast.error(data.message || (data.timed_out ? "Time's up!" : 'Incorrect'));
      }
    } catch (err) {
      const detail =
        err?.response?.data?.detail || 'Verification failed. Try starting again.';
      setError(typeof detail === 'string' ? detail : 'Verification failed.');
      setChallenge(null);
    } finally {
      setVerifying(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    submitAnswer(answer);
  };

  const isMemoryChallenge = challenge?.type === 'MEMORY';
  const showMemorySequence = isMemoryChallenge && !memoryReady;
  const maxTime = challenge?.time_limit_seconds || 30;
  const timerProgress =
    timeLeft == null ? 0 : Math.max(0, (timeLeft / maxTime) * 100);
  const timerColor =
    timeLeft == null ? 'text-slate-400' :
      timeLeft > maxTime * 0.5 ? 'text-emerald-400' :
        timeLeft > maxTime * 0.2 ? 'text-amber-400' : 'text-red-400';
  const timerBgColor =
    timeLeft == null ? 'bg-surface-800' :
      timeLeft > maxTime * 0.5 ? 'bg-emerald-500/20' :
        timeLeft > maxTime * 0.2 ? 'bg-amber-500/20' : 'bg-red-500/20';
  const timerBarColor =
    timeLeft == null ? 'bg-slate-600' :
      timeLeft > maxTime * 0.5 ? 'bg-emerald-500' :
        timeLeft > maxTime * 0.2 ? 'bg-amber-500' : 'bg-red-500';

  const attempts = stats.correct + stats.wrong;
  const accuracy = attempts ? Math.round((stats.correct / attempts) * 100) : 0;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            to="/dashboard"
            className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition mb-2"
          >
            <HiOutlineArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
          <h1 className="text-2xl font-bold text-white font-display flex items-center gap-2">
            <HiOutlinePuzzlePiece className="w-7 h-7 text-violet-400" />
            Practice Challenge
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Train with real puzzles. Practice does not affect wake streaks or habit logs.
          </p>
        </div>
      </div>

      {/* Session stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MiniStat label="Correct" value={stats.correct} />
        <MiniStat label="Wrong" value={stats.wrong} />
        <MiniStat label="Accuracy" value={`${accuracy}%`} />
        <MiniStat label="Points" value={stats.points} />
      </div>

      {/* Setup */}
      <div className="card space-y-5">
        <div>
          <p className="text-sm font-medium text-white mb-2">Challenge type</p>
          <div className="flex flex-wrap gap-2">
            {CHALLENGE_TYPES.map((t) => (
              <button
                key={t.value}
                type="button"
                disabled={!!challenge || loading}
                onClick={() => setChallengeType(t.value)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition ${challengeType === t.value
                    ? 'bg-violet-500/20 text-violet-200 border-violet-500/40'
                    : 'bg-surface-800 text-slate-400 border-surface-700/50 hover:text-white'
                  } disabled:opacity-50`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="text-sm font-medium text-white mb-2">Difficulty</p>
          <div className="flex flex-wrap gap-2">
            {DIFFICULTY_LEVELS.map((d) => (
              <button
                key={d}
                type="button"
                disabled={!!challenge || loading}
                onClick={() => setDifficulty(d)}
                className={`text-xs px-3 py-1.5 rounded-lg border capitalize transition ${difficulty === d
                    ? 'bg-amber-500/20 text-amber-200 border-amber-500/40'
                    : 'bg-surface-800 text-slate-400 border-surface-700/50 hover:text-white'
                  } disabled:opacity-50`}
              >
                {d}
              </button>
            ))}
          </div>
        </div>

        {!challenge && (
          <button
            type="button"
            onClick={startChallenge}
            disabled={loading}
            className="btn-primary w-full sm:w-auto"
          >
            {loading ? 'Loading…' : lastResult ? 'Next Challenge' : 'Start Practice'}
          </button>
        )}
      </div>

      {error && (
        <p className="text-sm text-red-400">{error}</p>
      )}

      {lastResult && !challenge && (
        <div
          className={`card flex items-start gap-3 border ${lastResult.correct
              ? 'border-emerald-500/30 bg-emerald-500/5'
              : 'border-orange-500/30 bg-orange-500/5'
            }`}
        >
          {lastResult.correct ? (
            <HiOutlineCheckCircle className="w-6 h-6 text-emerald-400 flex-shrink-0" />
          ) : (
            <HiOutlineXCircle className="w-6 h-6 text-orange-400 flex-shrink-0" />
          )}
          <div>
            <p className="text-sm font-medium text-white">{lastResult.message}</p>
            <p className="text-xs text-slate-400 mt-1 capitalize">
              {lastResult.challenge_type?.replace(/_/g, ' ')} · {lastResult.difficulty}
              {lastResult.score?.total_points
                ? ` · +${lastResult.score.total_points} pts`
                : ''}
            </p>
          </div>
        </div>
      )}

      {/* Active challenge */}
      {challenge && (
        <motion.div
          animate={{ x: shaking ? [0, -8, 8, -8, 8, 0] : 0 }}
          transition={shaking ? { duration: 0.45 } : undefined}
          className="card"
        >
          <div className={`flex items-center gap-2 px-4 py-2 rounded-xl ${timerBgColor} mb-4 w-fit`}>
            <HiOutlineClock className={`w-5 h-5 ${timerColor}`} />
            <span className={`text-lg font-bold font-mono ${timerColor}`}>
              {Math.floor((timeLeft ?? 0) / 60)}:{String((timeLeft ?? 0) % 60).padStart(2, '0')}
            </span>
            <span className="text-xs text-slate-500">/ {maxTime}s</span>
          </div>
          <div className="w-full bg-surface-800 rounded-full h-1.5 mb-5 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${timerBarColor}`}
              style={{ width: `${timerProgress}%` }}
            />
          </div>

          <div className="rounded-2xl border border-surface-700/50 bg-surface-900/40 p-5 mb-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-bold tracking-widest text-violet-400 uppercase">
                {(TYPE_LABEL[challenge.type] || challenge.type)} Challenge
              </span>
              <div className="flex items-center gap-2">
                {challenge.source === 'ai' && (
                  <span
                    title={`Generated by ${challenge.generator || 'AI'}`}
                    className="text-xs font-bold tracking-widest uppercase px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-300"
                  >
                    AI
                  </span>
                )}
                {challenge.difficulty && (
                  <span className="text-xs font-bold tracking-widest uppercase px-2 py-0.5 rounded-full bg-surface-700 text-slate-300">
                    {challenge.difficulty}
                  </span>
                )}
              </div>
            </div>

            {isMemoryChallenge ? (
              showMemorySequence ? (
                <div className="text-center py-4">
                  <p className="text-xs text-amber-300 mb-2">
                    Memorize — hiding in {memorySecondsLeft}s
                  </p>
                  <p className="text-2xl font-mono text-white tracking-widest break-all">
                    {challenge.prompt}
                  </p>
                </div>
              ) : (
                <div className="text-center py-4">
                  <p className="text-sm text-slate-400 mb-2">Sequence hidden — enter what you saw</p>
                  <p className="text-2xl font-mono text-slate-600 tracking-widest">
                    {'•'.repeat(Math.min(challenge.prompt?.length || 4, 12))}
                  </p>
                </div>
              )
            ) : (
              <p className="text-lg text-white leading-relaxed whitespace-pre-wrap">
                {challenge.prompt}
              </p>
            )}
          </div>

          {challenge.options ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {challenge.options.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  disabled={verifying || (isMemoryChallenge && !memoryReady)}
                  onClick={() => submitAnswer(opt)}
                  className="p-4 rounded-xl border border-surface-700/50 bg-surface-800/60 text-left text-white hover:border-violet-500/40 hover:bg-violet-500/10 transition disabled:opacity-50"
                >
                  {opt}
                </button>
              ))}
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-3">
              <input
                type="text"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                disabled={verifying || (isMemoryChallenge && !memoryReady)}
                placeholder={
                  isMemoryChallenge && !memoryReady
                    ? 'Memorize the sequence first…'
                    : 'Type your answer…'
                }
                className="input w-full"
                autoFocus
              />
              <button
                type="submit"
                disabled={
                  verifying ||
                  !answer.trim() ||
                  (isMemoryChallenge && !memoryReady)
                }
                className="btn-primary w-full"
              >
                {verifying ? 'Checking…' : 'Submit Answer'}
              </button>
            </form>
          )}

          <button
            type="button"
            onClick={() => {
              clearTimer();
              setChallenge(null);
              setAnswer('');
            }}
            className="mt-4 text-sm text-slate-500 hover:text-slate-300 transition"
          >
            Cancel this challenge
          </button>
        </motion.div>
      )}
    </div>
  );
}

function MiniStat({ label, value }) {
  return (
    <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 px-3 py-3">
      <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{label}</p>
      <p className="text-lg font-semibold text-white">{value}</p>
    </div>
  );
}
