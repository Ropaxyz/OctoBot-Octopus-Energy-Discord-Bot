# OctoBot: Octopus Energy Discord Bot

OctoBot is a Discord bot that integrates with the Octopus Energy API to provide users with their energy consumption data and costs directly within Discord. This bot allows users to set up their Octopus Energy accounts and retrieve detailed information about their electricity and gas usage.

## Features

- Easy account setup through Discord commands or button interactions
- Retrieval of energy consumption data for electricity and gas
- Generation of consumption charts for visual representation
- Calculation of energy costs based on consumption and tariff data
- Support for different time periods (7, 30, or 90 days)
- Secure storage of user API keys and account numbers

## Prerequisites

- Python 3.8+
- Discord Bot Token
- Octopus Energy API access

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/Ropaxyz/OctoBot-Octopus-Energy-Discord-Bot.git
   cd OctoBot-Octopus-Energy-Discord-Bot
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the root directory and add your Discord Bot Token:
   ```
   DISCORD_BOT_TOKEN=your_discord_bot_token_here
   ```

4. Update the channel ID:
   Open `octopus_energy_bot.py` and locate the line:
   ```python
   channel = bot.get_channel(1298013819188154398)
   ```
   Replace `1298013819188154398` with the ID of the channel where you want the setup button to appear in your Discord server.

## Usage

1. Run the bot:
   ```
   python octopus_energy_bot.py
   ```

2. Invite the bot to your Discord server using the OAuth2 URL generated in the Discord Developer Portal.

3. The bot will automatically post a setup button in the channel you specified. Users can click this button to set up their Octopus Energy account.

4. Alternatively, users can use the `/setup` command in Discord to configure their Octopus Energy account.

5. Use the `/get_energy_data` command to retrieve energy consumption data and charts.

## Commands

- `/setup`: Set up your Octopus Energy account credentials
- `/get_energy_data`: Retrieve energy consumption data and charts

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This bot is not officially affiliated with Octopus Energy. Use at your own risk.

## Acknowledgements

- [Octopus Energy API](https://developer.octopus.energy/docs/api/)
- [Discord.py](https://discordpy.readthedocs.io/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [Matplotlib](https://matplotlib.org/)

## Support

If you encounter any issues or have questions, please [open an issue](https://github.com/Ropaxyz/OctoBot-Octopus-Energy-Discord-Bot/issues) on GitHub.

You can also join our Discord server for support and discussions: [https://discord.gg/3ZCtSyMCp3](https://discord.gg/3ZCtSyMCp3)

## Author

[Ropaxyz](https://github.com/Ropaxyz)

Discord: ross_._
