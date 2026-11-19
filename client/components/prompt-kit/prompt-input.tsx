"use client";

import React, { createContext, useContext, useRef, useEffect, useState } from "react";

interface PromptInputContextType {
  value: string;
  setValue: (value: string) => void;
  isLoading: boolean;
  onSubmit?: () => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}

const PromptInputContext = createContext<PromptInputContextType | null>(null);

export function usePromptInput() {
  const context = useContext(PromptInputContext);
  if (!context) {
    throw new Error("usePromptInput must be used within a <PromptInput />");
  }
  return context;
}

interface PromptInputProps {
  value?: string;
  onValueChange?: (val: string) => void;
  defaultValue?: string;
  isLoading?: boolean;
  onSubmit?: () => void;
  children: React.ReactNode;
  className?: string;
}

export function PromptInput({
  value: controlledValue,
  onValueChange,
  defaultValue = "",
  isLoading = false,
  onSubmit,
  children,
  className = "",
}: PromptInputProps) {
  const [uncontrolledValue, setUncontrolledValue] = useState(defaultValue);
  const isControlled = controlledValue !== undefined;
  const value = isControlled ? controlledValue : uncontrolledValue;
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const setValue = (newVal: string) => {
    if (!isControlled) {
      setUncontrolledValue(newVal);
    }
    onValueChange?.(newVal);
  };

  return (
    <PromptInputContext.Provider
      value={{
        value,
        setValue,
        isLoading,
        onSubmit,
        textareaRef,
      }}
    >
      <div
        className={`relative flex flex-col w-full rounded-[22px] bg-surface border border-line hover:border-line-strong focus-within:border-ink/40 focus-within:ring-4 focus-within:ring-amber-100 transition-all duration-200 shadow-lift ${className}`}
      >
        {children}
      </div>
    </PromptInputContext.Provider>
  );
}

interface PromptInputTextareaProps
  extends Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange"> {
  maxHeight?: number;
}

export function PromptInputTextarea({
  placeholder = "Enter a brand website URL or prompt...",
  maxHeight = 200,
  className = "",
  onKeyDown,
  ...props
}: PromptInputTextareaProps) {
  const { value, setValue, onSubmit, isLoading, textareaRef } = usePromptInput();

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [value, maxHeight, textareaRef]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading && value.trim()) {
        onSubmit?.();
      }
    }
    onKeyDown?.(e);
  };

  return (
    <textarea
      ref={textareaRef}
      rows={1}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={handleKeyDown}
      placeholder={placeholder}
      className={`w-full bg-transparent px-4 pt-4 pb-2 text-ink placeholder:text-faint text-[15px] sm:text-base leading-relaxed resize-none outline-none border-none focus:outline-none focus:ring-0 font-sans tracking-normal ${className}`}
      {...props}
    />
  );
}

interface PromptInputActionsProps {
  children: React.ReactNode;
  className?: string;
}

export function PromptInputActions({
  children,
  className = "",
}: PromptInputActionsProps) {
  return (
    <div
      className={`flex items-center justify-between gap-3 px-3.5 pb-3 pt-1  ${className}`}
    >
      {children}
    </div>
  );
}

interface PromptInputActionProps {
  children: React.ReactNode;
  className?: string;
  tooltip?: string;
}

export function PromptInputAction({
  children,
  className = "",
  tooltip,
}: PromptInputActionProps) {
  return (
    <div className={`relative flex items-center ${className}`} title={tooltip}>
      {children}
    </div>
  );
}
