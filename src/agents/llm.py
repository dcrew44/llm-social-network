"""LLM client abstraction for agent cognition."""

import json
from typing import Any

import requests


class OllamaClient:
    """Client for Ollama local LLM API."""

    def __init__(self, model: str = "llama3.2:3b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 150,
        system: str | None = None,
    ) -> str:
        """
        Generate text from a prompt.

        Args:
            prompt: The user prompt
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate
            system: Optional system prompt

        Returns:
            Generated text
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            return result["message"]["content"].strip()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama API error: {e}") from e

    def generate_json(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 150,
        system: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate JSON output from a prompt.

        Args:
            prompt: The user prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            system: Optional system prompt

        Returns:
            Parsed JSON object
        """
        # Add JSON formatting instruction
        full_prompt = f"{prompt}\n\nRespond with valid JSON only, no other text."

        response_text = self.generate(
            prompt=full_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
        )

        # Try to extract JSON from response
        # Sometimes models wrap JSON in markdown code blocks
        text = response_text.strip()

        # Remove markdown code fence if present
        if text.startswith("```"):
            # Find first newline after ```
            start = text.find("\n") + 1
            # Find closing ```
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()
            else:
                text = text[start:].strip()

        # Remove 'json' language identifier if present
        if text.lower().startswith("json"):
            text = text[4:].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {text}") from e
