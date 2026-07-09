import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HiOutlineBellAlert } from 'react-icons/hi2';
import toast from 'react-hot-toast';
import useActiveAlarmStore from '../store/activeAlarmStore';

export default function ActiveAlarmModal() {
  const { isRinging, challenge, isLoading, error, verifyAndDismiss, snoozeAlarm } = useActiveAlarmStore();
  const [answer, setAnswer] = useState('');
  const [failedAttempts, setFailedAttempts] = useState(0);
  const startTimeRef = useRef(null);
  const audioRef = useRef(null);
  
  // Setup audio context for standard beep since we don't have an mp3
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
        oscillator.frequency.setValueAtTime(800, audioCtx.currentTime); // 800Hz beep
        
        gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime); // Volume
        gainNode.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.5);
        
        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        
        oscillator.start();
        oscillator.stop(audioCtx.currentTime + 0.5);
      };
      
      // Beep every second
      playBeep();
      intervalId = setInterval(playBeep, 1000);
      
      // Prevent scrolling
      document.body.style.overflow = 'hidden';
    }
    
    return () => {
      if (intervalId) clearInterval(intervalId);
      if (audioCtx) audioCtx.close();
      document.body.style.overflow = 'auto';
    };
  }, [isRinging]);
  
  useEffect(() => {
    if (challenge && !startTimeRef.current) {
      startTimeRef.current = Date.now();
    }
  }, [challenge]);

  // Show error toast if verification fails
  useEffect(() => {
    if (error) {
      toast.error(error);
      setAnswer('');
      setFailedAttempts(prev => prev + 1);
    }
  }, [error]);

  if (!isRinging) {
    if (startTimeRef.current) {
      startTimeRef.current = null;
      setFailedAttempts(0);
    }
    return null;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!answer.trim()) return;
    
    const timeTaken = startTimeRef.current ? Math.floor((Date.now() - startTimeRef.current) / 1000) : 0;
    await verifyAndDismiss(answer, timeTaken, failedAttempts);
  };

  const handleSnooze = async () => {
    const res = await snoozeAlarm();
    if (res.success) {
      toast.success("Alarm snoozed");
      startTimeRef.current = null;
      setFailedAttempts(0);
    }
  };
  
  const handleOptionClick = async (opt) => {
    const timeTaken = startTimeRef.current ? Math.floor((Date.now() - startTimeRef.current) / 1000) : 0;
    await verifyAndDismiss(opt, timeTaken, failedAttempts);
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/90 backdrop-blur-md">
        <motion.div 
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          className="w-full max-w-lg bg-slate-900 border border-slate-700 rounded-3xl p-8 shadow-2xl relative overflow-hidden"
        >
          {/* Animated background rings */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-accent-500/20 rounded-full blur-3xl animate-ping" style={{ animationDuration: '2s' }} />
          
          <div className="relative z-10 flex flex-col items-center text-center">
            <div className="w-20 h-20 bg-accent-500/20 rounded-2xl flex items-center justify-center mb-6 text-accent-400 animate-bounce">
              <HiOutlineBellAlert className="w-10 h-10" />
            </div>
            
            <h2 className="text-3xl font-display font-bold text-white mb-2">WAKE UP!</h2>
            <p className="text-slate-400 mb-8">Solve the challenge to turn off the alarm.</p>
            
            {!challenge ? (
              <div className="w-10 h-10 border-4 border-accent-500 border-t-transparent rounded-full animate-spin my-8" />
            ) : (
              <div className="w-full">
                <div className="bg-slate-800/50 rounded-2xl p-6 mb-8 border border-slate-700/50">
                  <span className="text-xs font-bold tracking-widest text-accent-400 uppercase mb-2 block">
                    {challenge.type} CHALLENGE
                  </span>
                  
                  {challenge.type === 'MEMORY' ? (
                    <div className="text-4xl font-bold tracking-[1em] text-white my-6">
                      {challenge.prompt}
                    </div>
                  ) : (
                    <div className="text-2xl font-bold text-white my-4">
                      {challenge.prompt}
                    </div>
                  )}
                </div>
                
                {challenge.options ? (
                  <div className="grid grid-cols-2 gap-4 mb-6">
                    {challenge.options.map((opt, i) => (
                      <button 
                        key={i}
                        onClick={() => handleOptionClick(opt)}
                        disabled={isLoading}
                        className="btn-secondary h-16 text-xl font-bold bg-slate-800 hover:bg-slate-700 border-slate-600 hover:border-slate-500"
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                ) : (
                  <form onSubmit={handleSubmit} className="mb-6">
                    <input 
                      type="text"
                      value={answer}
                      onChange={(e) => setAnswer(e.target.value)}
                      placeholder="Type your answer here..."
                      className="input w-full text-center text-xl h-14 mb-4"
                      autoFocus
                    />
                    <button 
                      type="submit" 
                      disabled={isLoading || !answer.trim()}
                      className="btn-primary w-full h-14 text-lg font-bold"
                    >
                      {isLoading ? 'Verifying...' : 'Turn Off Alarm'}
                    </button>
                  </form>
                )}
                
                <button 
                  onClick={handleSnooze}
                  disabled={isLoading}
                  className="text-slate-500 hover:text-white underline decoration-slate-600 hover:decoration-white underline-offset-4 transition text-sm font-medium"
                >
                  Snooze
                </button>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
