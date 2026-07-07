import os
import json
import time
from dotenv import load_dotenv
from core.error_handling import call_ai_proxy_safe

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE)

def generate_custom_email(company_name, role, user_skills, base_template):
    """
    Attempts to use OpenAI API, then Gemini, then Claude to generate a personalized email.
    Gracefully falls back to the base_template if all fail.
    """
    import time
    
    custom_instructions = os.getenv("AI_CUSTOM_PROMPT", "")
    
    system_prompt = "You are an expert career coach. Rewrite the provided job application paragraph. Rules: 1) Seamlessly integrate company name and role. 2) Align skills with the role. 3) Keep it highly professional and enthusiastic. 4) CRITICAL: NO greetings, NO sign-offs, NO placeholders, NO conversational filler. Return ONLY the rewritten paragraph."
    
    user_prompt = f"Company:{company_name}\nRole:{role}\nSkills:{user_skills}\nCustom:{custom_instructions if custom_instructions else 'None'}\n\nRewrite this paragraph:\n{base_template}"

    # 1. Try GPT (OpenAI or Proxy)
    gpt_key = os.getenv("OPENAI_API_KEY")
    if gpt_key:
        try:
            import requests
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            if not base_url.endswith("/chat/completions"):
                endpoint = f"{base_url}/chat/completions"
            else:
                endpoint = base_url
                
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o")
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {gpt_key}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/event-stream"
            }
            
            data = {
                "model": model_name,
                "messages": [
                    {"role": "user", "content": f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\n{user_prompt}"}
                ]
            }
            
            for attempt in range(2):
                result = call_ai_proxy_safe(endpoint, data, headers)
                if result.ok:
                    try:
                        parsed = json.loads(result.detail)
                        content = parsed.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        if content:
                            print("   [AI Engine] Successfully generated with GPT/Proxy")
                            return content
                    except json.JSONDecodeError:
                        print("   [AI Engine] Invalid JSON from proxy")
                else:
                    if result.retriable and attempt < 1:
                        print(f"   ⚠️ Transient AI proxy error ({result.detail}), retrying...")
                        time.sleep(2)
                    else:
                        print(f"   [AI Engine] GPT/Proxy failed: {result.detail}")
                        break
        except Exception as e:
            print(f"   [AI Engine] GPT request setup error: {e}")

    # 2. Try Gemini
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            model = genai.GenerativeModel(model_name, system_instruction=system_prompt)
            
            for attempt in range(2):
                try:
                    response = model.generate_content(user_prompt)
                    if response.text:
                        print("   [AI Engine] Successfully generated with Gemini")
                        return response.text.strip()
                except Exception as e:
                    if attempt < 1:
                        time.sleep(2)
                    else:
                        print(f"   [AI Engine] Gemini failed: {e}")
        except ImportError:
            print("   [AI Engine] google.generativeai package not installed, skipping Gemini.")
        except Exception as e:
            print(f"   [AI Engine] Gemini error: {e}")

    # 3. Try Claude (Anthropic)
    claude_key = os.getenv("ANTHROPIC_API_KEY")
    if claude_key:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=claude_key)
            
            for attempt in range(2):
                try:
                    response = client.messages.create(
                        model="claude-3-haiku-20240307",
                        max_tokens=1000,
                        system=system_prompt,
                        messages=[{"role": "user", "content": user_prompt}]
                    )
                    if response.content:
                        print("   [AI Engine] Successfully generated with Claude")
                        return response.content[0].text.strip()
                except Exception as e:
                    if attempt < 1:
                        time.sleep(2)
                    else:
                        print(f"   [AI Engine] Claude failed: {e}")
        except ImportError:
            print("   [AI Engine] anthropic package not installed, skipping Claude.")
        except Exception as e:
            print(f"   [AI Engine] Claude error: {e}")

    print("   [AI Engine] All AI engines failed or keys missing. Falling back to template.")
    return base_template
