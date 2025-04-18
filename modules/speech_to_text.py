#!/usr/bin/env python3

from typing import Dict, List, Tuple, Any, Optional
import os
import tempfile
from groq import Groq
from modules.config import SAMPLE_RATE, CHANNELS, GROQ_MODEL, TRIGGER_PHRASE, STOP_PHRASE
from modules.agents import SpeakerDiarizationAgent

class SpeechToText:
    """
    Uses Groq API to transcribe audio to text.
    Can also perform speaker diarization if enabled.
    """
    def __init__(self, model_name="whisper-large-v3", use_diarization=False):
        self.client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        self.model = model_name
        
        self.use_diarization = use_diarization
        self.diarization_agent = None
        self.user_reference_path = None
        
        if use_diarization:
            self.diarization_agent = SpeakerDiarizationAgent()
    
    def set_user_reference(self, reference_path: str) -> bool:
        """Set the user's voice reference for speaker diarization"""
        if not self.use_diarization or self.diarization_agent is None:
            return False
            
        result = self.diarization_agent.capture_user_reference(reference_path)
        if result:
            self.user_reference_path = reference_path
            return True
        return False
    
    def _convert_audio_to_base64(self, audio_file: str) -> str:
        """Convert audio file to base64 for API submission"""
        import base64
        with open(audio_file, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    def transcribe(self, audio_file: str, detect_trigger_only=False) -> str:
        """
        Transcribe audio to text without speaker diarization.
        """
        try:
            import requests
            import json
            
            with open(audio_file, "rb") as audio:
                headers = {
                    "Authorization": f"Bearer {os.environ.get('GROQ_API_KEY')}",
                }
                
                files = {
                    "file": audio,
                }
                
                data = {
                    "model": self.model,
                    "language": "en", 
                }
                
                if detect_trigger_only:
                    data["prompt"] = f"Focus on detecting the phrase '{TRIGGER_PHRASE}' or '{STOP_PHRASE}' if present."
                    data["temperature"] = 0
                
                response = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data
                )
                
                if response.status_code != 200:
                    print(f"Error in Groq transcription: Status {response.status_code} - {response.text}")
                    return ""
                    
                result = response.json()
                transcription = result.get("text", "").strip()
                
                noise_words = ["you", "my", "me", "i", "a", "the", "um", "uh", "ah", "oh", "eh"]
                
                hallucination_phrases = ["thank you", "thanks", "thank", "you're welcome"]
                
                cleaned_text = transcription.lower()
                for phrase in hallucination_phrases:
                    if phrase in cleaned_text:
                        print(f"Filtering out hallucinated phrase in transcription: '{transcription}'")
                        return ""
                
                words = cleaned_text.split()
                if len(words) == 1:
                    clean_word = words[0].rstrip('.!?,:;')
                    if clean_word in noise_words:
                        print(f"Filtering out noise word in transcription: '{transcription}'")
                        return ""
                
                if transcription.lower() == "you" or transcription.lower() in ["you.", "you?", "you!"]:
                    print(f"Filtering out single word 'you': '{transcription}'")
                    return ""
                
                confidence = result.get("confidence", 1.0)
                if confidence < 0.7:  # Adjust threshold as needed
                    print(f"Low confidence transcription ({confidence}): {transcription}")
                    return ""
                
                return transcription
        
        except Exception as e:
            print(f"Error in Groq transcription: {e}")
            import traceback
            traceback.print_exc()
            return ""
    
    def transcribe_with_speakers(self, audio_file: str, num_speakers: int = 2) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Transcribe audio to text with speaker diarization.
        """
        if not self.use_diarization or self.diarization_agent is None:
            print("Speaker diarization is not enabled, falling back to regular transcription")
            return self.transcribe(audio_file), []
        
        transcript = self.transcribe(audio_file)
        
        if not transcript:
            return "", []
        
        segments = [{"text": transcript, "start": 0.0, "end": 10.0}]  
        
        segments_with_speakers = self.diarization_agent.process_conversation(
            audio_file, 
            segments, 
            num_speakers=num_speakers
        )
        
        filtered_segments = []
        noise_words = ["you", "my", "me", "i", "a", "the", "um", "uh", "ah", "oh", "eh"]
        hallucination_phrases = ["thank you", "thanks", "thank", "you're welcome"]
        
        for segment in segments_with_speakers:
            segment_text = segment.get("text", "").strip().lower()
            
            if not segment_text:
                continue
                
            hallucinated = False
            for phrase in hallucination_phrases:
                if phrase in segment_text:
                    print(f"Filtering out hallucinated segment: '{segment_text}'")
                    hallucinated = True
                    break
            
            if hallucinated:
                continue
                
            words = segment_text.split()
            if len(words) == 1:
                clean_word = words[0].rstrip('.!?,:;')
                if clean_word in noise_words or len(clean_word) < 3:
                    print(f"Filtering out noise segment: '{segment_text}'")
                    continue
            
            filtered_segments.append(segment)
        
        if not filtered_segments:
            return "", []
        
        formatted_segments = []
        current_speaker = None
        for segment in filtered_segments:
            if segment["speaker"] != current_speaker:
                current_speaker = segment["speaker"]
                formatted_segments.append(f"\n[{current_speaker}]: {segment['text']}")
            else:
                formatted_segments.append(segment["text"])
        
        full_transcript = " ".join(formatted_segments)
        
        return full_transcript, filtered_segments 