"""Agentverse/local service entrypoint. Importing this file starts no service."""

from tool_offer_agent.chat import create_agent

if __name__ == "__main__":
    agent = create_agent()
    agent.run()
