# -*- coding: utf-8 -*-
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import aiohttp
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
import io
from dotenv import load_dotenv
import os
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.exceptions import TransportQueryError
import logging
from cachetools import TTLCache
from aiohttp import ClientTimeout
import pytz
import backoff
from asyncio import TimeoutError
import pandas as pd
from dataclasses import dataclass

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL', "sqlite:///user_data.db")
SETUP_CHANNEL_ID = int(os.getenv('SETUP_CHANNEL_ID', '1298013819188154398'))
API_TIMEOUT = 60
MAX_RETRIES = 3
BACKOFF_MAX_TIME = 120
CACHE_TTL = 3600  # 1 hour cache TTL

# Initialize cache
response_cache = TTLCache(maxsize=100, ttl=CACHE_TTL)

# Database models
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, unique=True)
    api_key = Column(String)
    account_number = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, onupdate=datetime.utcnow)

# Initialize database
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# API endpoints
class APIEndpoints:
    GRAPHQL = "https://api.octopus.energy/v1/graphql/"
    REST = "https://api.octopus.energy/v1/"

# GraphQL queries
class GraphQLQueries:
    OBTAIN_TOKEN = gql("""
    mutation obtainKrakenToken($input: ObtainJSONWebTokenInput!) {
        obtainKrakenToken(input: $input) {
            token
        }
    }
    """)

    ACCOUNT_INFO = gql("""
    query Account($accountNumber: String!) {
        account(accountNumber: $accountNumber) {
            number
            properties {
                electricityMeterPoints {
                    mpan
                    meters {
                        serialNumber
                        consumptionUnits
                    }
                    agreements {
                        validFrom
                        validTo
                        tariff {
                            ... on TariffType {
                                displayName
                                productCode
                                fullName
                            }
                        }
                    }
                }
                gasMeterPoints {
                    mprn
                    meters {
                        serialNumber
                        consumptionUnits
                    }
                    agreements {
                        validFrom
                        validTo
                        tariff {
                            ... on TariffType {
                                displayName
                                productCode
                                fullName
                            }
                        }
                    }
                }
            }
        }
    }
    """)

@dataclass
class EnergyData:
    fuel_type: str
    consumption: list
    tariff: list
    standing_charge: float
    summary: str

class APIClient:
    def __init__(self, token: str):
        self.token = token
        self.timeout = ClientTimeout(
            total=60,      # Total timeout
            connect=10,    # Connection timeout
            sock_read=30   # Socket read timeout
        )
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    @backoff.on_exception(
        backoff.expo,
        (TimeoutError, TransportQueryError, aiohttp.ClientError),
        max_tries=3,
        max_time=30
    )
    async def get_consumption_data(self, fuel_type, identifier, serial_number, from_date, to_date):
        cache_key = f"consumption_{fuel_type}_{identifier}_{from_date}_{to_date}"
        if cache_key in response_cache:
            return response_cache[cache_key]
        
        url = f"{APIEndpoints.REST}{fuel_type}-meter-points/{identifier}/meters/{serial_number}/consumption/"
        params = {
            'period_from': from_date.isoformat(),
            'period_to': to_date.isoformat(),
            'group_by': 'day'
        }
        headers = {
            'Authorization': f'JWT {self.token}',
            'Accept': 'application/json'
        }
        
        try:
            async with self.session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get('results', [])
                    
                    if results:
                        # Sort results by date
                        results.sort(key=lambda x: x['interval_start'])
                        
                        # Find the latest data point
                        latest_reading = results[-1]
                        latest_date = datetime.fromisoformat(latest_reading['interval_start'])
                        current_time = datetime.now(pytz.UTC)
                        delay = current_time - latest_date
                        
                        logger.info(f"\n{fuel_type.capitalize()} Data Status:")
                        logger.info(f"Latest reading: {latest_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        logger.info(f"Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        logger.info(f"Data delay: {delay.days} days, {delay.seconds//3600} hours")
                        
                        if delay.days >= 2:
                            logger.warning(f"Data is more than 48 hours old. This might indicate an issue with meter readings.")
                    
                    response_cache[cache_key] = results
                    return results
                    
        except aiohttp.ClientError as e:
            logger.error(f"API request failed: {str(e)}")
            raise

    async def get_tariff_data(self, fuel_type, product_code, from_date, to_date):
        url = f"{APIEndpoints.REST}products/{product_code}/{fuel_type}-tariffs/{'G' if fuel_type == 'gas' else 'E'}-1R-{product_code}-{'G' if fuel_type == 'gas' else 'E'}/standard-unit-rates/"
        params = {
            'period_from': from_date.isoformat(),
            'period_to': to_date.isoformat()
        }
        headers = {
            'Authorization': f'JWT {self.token}',
            'Accept': 'application/json'
        }

        async with self.session.get(url, params=params, headers=headers) as response:
            response.raise_for_status()
            data = await response.json()
            return data['results']

    async def get_standing_charge(self, fuel_type, product_code, from_date, to_date):
        url = f"{APIEndpoints.REST}products/{product_code}/{fuel_type}-tariffs/{'G' if fuel_type == 'gas' else 'E'}-1R-{product_code}-{'G' if fuel_type == 'gas' else 'E'}/standing-charges/"
        params = {
            'period_from': from_date.isoformat(),
            'period_to': to_date.isoformat()
        }
        headers = {
            'Authorization': f'JWT {self.token}',
            'Accept': 'application/json'
        }

        async with self.session.get(url, params=params, headers=headers) as response:
            response.raise_for_status()
            data = await response.json()
            return data['results'][0]['value_inc_vat'] / 100

async def get_auth_token(api_key: str) -> str:
    transport = AIOHTTPTransport(
        url=APIEndpoints.GRAPHQL,
        timeout=30
    )
    
    try:
        async with Client(
            transport=transport,
            fetch_schema_from_transport=True,
            execute_timeout=30
        ) as session:
            result = await session.execute(
                GraphQLQueries.OBTAIN_TOKEN,
                variable_values={"input": {"APIKey": api_key}}
            )
            return result['obtainKrakenToken']['token']
    except Exception as e:
        logger.error(f"Failed to get auth token: {str(e)}")
        raise ValueError("Failed to authenticate with Octopus Energy API")

async def get_account_info(token: str, account_number: str):
    transport = AIOHTTPTransport(
        url=APIEndpoints.GRAPHQL,
        headers={'Authorization': f'JWT {token}'},
        timeout=30
    )
    
    try:
        async with Client(
            transport=transport,
            fetch_schema_from_transport=True,
            execute_timeout=30
        ) as session:
            result = await session.execute(
                GraphQLQueries.ACCOUNT_INFO,
                variable_values={"accountNumber": account_number}
            )
            if not result.get('account'):
                raise ValueError("Account not found")
            return result['account']
    except Exception as e:
        logger.error(f"Failed to get account info: {str(e)}")
        raise ValueError("Failed to retrieve account information")

async def process_meter_point(client: APIClient, fuel_type: str, meter_point: dict, from_date: datetime, to_date: datetime) -> EnergyData:
    try:
        identifier = meter_point['mpan' if fuel_type == 'electricity' else 'mprn']
        serial_number = meter_point['meters'][0]['serialNumber']
        product_code = meter_point['agreements'][0]['tariff']['productCode']

        consumption_data = await client.get_consumption_data(fuel_type, identifier, serial_number, from_date, to_date)
        tariff_data = await client.get_tariff_data(fuel_type, product_code, from_date, to_date)
        standing_charge = await client.get_standing_charge(fuel_type, product_code, from_date, to_date)

        if consumption_data and tariff_data and standing_charge is not None:
            summary = calculate_summary(fuel_type, consumption_data, tariff_data, standing_charge, from_date, to_date)
            return EnergyData(
                fuel_type=fuel_type,
                consumption=consumption_data,
                tariff=tariff_data,
                standing_charge=standing_charge,
                summary=summary
            )
    except Exception as e:
        logger.error(f"Error processing {fuel_type} meter point: {str(e)}")
        raise

def calculate_summary(fuel_type: str, consumption_data: list, tariff_data: list, standing_charge: float, from_date: datetime, to_date: datetime) -> str:
    total_cost = 0
    total_consumption = 0
    total_days = (to_date - from_date).days

    logger.info(f"\nProcessing {fuel_type} data for {total_days} days")

    for day in consumption_data:
        date = datetime.fromisoformat(day['interval_start']).date()
        raw_consumption = day['consumption']
        
        if fuel_type == 'gas':
            # Detailed gas conversion logging
            logger.info(f"\nGas conversion for {date}:")
            logger.info(f"Raw gas value: {raw_consumption} m³")
            
            # Convert m³ to kWh using the formula
            kwh_conversion = raw_consumption * 39.5  # Volume correction factor
            logger.info(f"After volume correction: {kwh_conversion}")
            
            kwh_conversion = kwh_conversion * 1.02264  # Pressure correction
            logger.info(f"After pressure correction: {kwh_conversion}")
            
            consumption = kwh_conversion / 3.6  # Final conversion to kWh
            logger.info(f"Final kWh value: {consumption}")
        else:
            consumption = raw_consumption

        total_consumption += consumption
        
        applicable_rate = next(
            (rate for rate in tariff_data if datetime.fromisoformat(rate['valid_from']).date() <= date),
            None
        )
        
        if applicable_rate:
            rate = applicable_rate['value_inc_vat'] / 100
            cost = consumption * rate
            total_cost += cost
            logger.info(f"{fuel_type} cost for {date}: £{cost:.2f} (rate: {rate:.4f})")

    total_standing_charge = standing_charge * total_days
    total_cost += total_standing_charge

    summary = (
        f"Total {fuel_type} consumption: {total_consumption:.2f} kWh\n"
        f"Total {fuel_type} unit cost: £{(total_cost - total_standing_charge):.2f}\n"
        f"Total standing charge: £{total_standing_charge:.2f}\n"
        f"Total {fuel_type} cost: £{total_cost:.2f}"
    )
    
    logger.info(f"\nFinal {fuel_type} Summary:")
    logger.info(summary)
    
    return summary

class SetupModal(discord.ui.Modal, title="Set Up Octopus Energy Account"):
    api_key = discord.ui.TextInput(
        label="Octopus Energy API Key",
        style=discord.TextStyle.short,
        placeholder="sk_live_..."
    )
    account_number = discord.ui.TextInput(
        label="Account Number",
        style=discord.TextStyle.short,
        placeholder="A-1234567"
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if not self.api_key.value.startswith('sk_live_'):
                await interaction.response.send_message(
                    "Invalid API key format. It should start with 'sk_live_'",
                    ephemeral=True
                )
                return

            if not self.account_number.value.startswith('A-'):
                await interaction.response.send_message(
                    "Invalid account number format. It should start with 'A-'",
                    ephemeral=True
                )
                return

            session = Session()
            try:
                user = session.query(User).filter_by(discord_id=str(interaction.user.id)).first()
                if not user:
                    user = User(discord_id=str(interaction.user.id))
                    session.add(user)
                user.api_key = self.api_key.value
                user.account_number = self.account_number.value
                session.commit()
                
                await interaction.response.send_message(
                    "✅ Your Octopus Energy account has been set up successfully!",
                    ephemeral=True
                )
            except Exception as e:
                logger.error(f"Database error during setup: {str(e)}")
                session.rollback()
                await interaction.response.send_message(
                    "❌ An error occurred while saving your account details.",
                    ephemeral=True
                )
            finally:
                session.close()

        except Exception as e:
            logger.error(f"Setup error: {str(e)}")
            await interaction.response.send_message(
                "❌ An unexpected error occurred during setup.",
                ephemeral=True
            )

class SetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Set Up Octopus Energy Account",
        style=discord.ButtonStyle.primary,
        custom_id="setup_button"
    )
    async def setup_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "How would you like to set up your account?",
            view=SetupChoiceView(),
            ephemeral=True
        )

class SetupChoiceView(discord.ui.View):
    def __init__(self):
        super().__init__()

    @discord.ui.button(
        label="Set up via DM",
        style=discord.ButtonStyle.primary
    )
    async def dm_setup(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "I'll send you a DM to set up your account.",
            ephemeral=True
        )
        try:
            await interaction.user.send(
                "Let's set up your Octopus Energy account. Please use the /setup command here."
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I couldn't send you a DM. Please check if you have DMs enabled for this server.",
                ephemeral=True
            )

    @discord.ui.button(
        label="Set up here",
        style=discord.ButtonStyle.secondary
    )
    async def channel_setup(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_modal(SetupModal())

def generate_chart(data: EnergyData) -> io.BytesIO:
    # Sort data by date and filter out today
    today = datetime.now(pytz.UTC).date()
    consumption_data = sorted(
        [d for d in data.consumption if datetime.fromisoformat(d['interval_start']).date() < today],
        key=lambda x: x['interval_start']
    )
    
    dates = [datetime.fromisoformat(day['interval_start']).date() for day in consumption_data]
    values = [day['consumption'] for day in consumption_data]
    
    # Set style
    sns.set_style("whitegrid")
    
    plt.figure(figsize=(12, 6))
    plt.plot(dates, values, marker='o')
    
    # Use appropriate units based on fuel type
    units = "m³" if data.fuel_type == "gas" else "kWh"
    plt.title(f'{data.fuel_type.capitalize()} Consumption')
    plt.xlabel('Date')
    plt.ylabel(f'Consumption ({units})')
    plt.xticks(rotation=45)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=300, bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return buf

def generate_combined_chart(energy_data_list: list) -> io.BytesIO:
    sns.set_style("whitegrid")
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    colors = {
        'electricity': '#007bff',  # Blue
        'gas': '#ff7f0e'          # Orange
    }
    
    for data in energy_data_list:
        # Sort data by date and filter out today
        today = datetime.now(pytz.UTC).date()
        consumption_data = sorted(
            [d for d in data.consumption if datetime.fromisoformat(d['interval_start']).date() < today],
            key=lambda x: x['interval_start']
        )
        
        if consumption_data:
            dates = [datetime.fromisoformat(day['interval_start']).date() for day in consumption_data]
            values = [day['consumption'] for day in consumption_data]
            
            if data.fuel_type == 'electricity':
                ax1.plot(dates, values, marker='o', color=colors[data.fuel_type], 
                        label=f'{data.fuel_type.capitalize()}')
                ax1.set_ylabel('Electricity Consumption (kWh)')
            else:
                ax2.plot(dates, values, marker='o', color=colors[data.fuel_type], 
                        label=f'{data.fuel_type.capitalize()}')
                ax2.set_ylabel('Gas Consumption (m³)')
    
    ax1.set_title('Electricity Consumption')
    ax2.set_title('Gas Consumption')
    
    for ax in [ax1, ax2]:
        ax.grid(True)
        ax.tick_params(axis='x', rotation=45)
        ax.legend()
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=300, bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return buf
@bot.tree.command(name="setup", description="Set up your Octopus Energy account")
async def setup(interaction: discord.Interaction):
    await interaction.response.send_modal(SetupModal())

@bot.tree.command(
    name="get_energy_data",
    description="Get your energy consumption data and cost analysis"
)
@app_commands.choices(
    energy_type=[
        app_commands.Choice(name="Electricity", value="electricity"),
        app_commands.Choice(name="Gas", value="gas"),
        app_commands.Choice(name="Both", value="both")
    ],
    time_period=[
        app_commands.Choice(name="Last 7 days", value="7"),
        app_commands.Choice(name="Last 30 days", value="30"),
        app_commands.Choice(name="Last 90 days", value="90")
    ]
)
@app_commands.checks.cooldown(1, 60)
async def get_energy_data(
    interaction: discord.Interaction,
    energy_type: app_commands.Choice[str],
    time_period: app_commands.Choice[str]
):
    try:
        await interaction.response.defer()
        logger.info(f"Processing energy data request for user {interaction.user.id}")

        # Add warning message for 7-day reports
        if time_period.value == "7":
            await interaction.followup.send(
                "⚠️ **Please Note**: The 7-day report may show incomplete or inaccurate data due to delays in meter readings. "
                "For more accurate consumption data, please use the 30-day report instead.",
                ephemeral=True
            )

        session = Session()
        user = session.query(User).filter_by(discord_id=str(interaction.user.id)).first()
        session.close()

        if not user:
            await interaction.followup.send(
                "❌ You haven't set up your Octopus Energy account yet. Use /setup to get started.",
                ephemeral=True
            )
            return

        try:
            # Calculate date range excluding current day
            to_date = datetime.now(pytz.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            from_date = to_date - timedelta(days=int(time_period.value))
            
            # Adjust to_date to end of yesterday
            to_date = to_date - timedelta(days=1)
            
            logger.info(f"Requesting data from {from_date} to {to_date}")

            # Get authentication token
            token = await get_auth_token(user.api_key)
            # Get account info
            account_data = await get_account_info(token, user.account_number)

            async with APIClient(token) as client:
                tasks = []
                properties = account_data['properties']

                if energy_type.value in ['electricity', 'both']:
                    for meter_point in properties[0].get('electricityMeterPoints', []):
                        tasks.append(process_meter_point(client, 'electricity', meter_point, from_date, to_date))

                if energy_type.value in ['gas', 'both']:
                    for meter_point in properties[0].get('gasMeterPoints', []):
                        tasks.append(process_meter_point(client, 'gas', meter_point, from_date, to_date))

                results = await asyncio.gather(*tasks, return_exceptions=True)
                valid_results = [r for r in results if isinstance(r, EnergyData)]

                if not valid_results:
                    error_msg = "No energy data available for the selected period. "
                    error_msg += "Note that there is typically a delay of 1-2 days in receiving energy consumption data."
                    await interaction.followup.send(error_msg, ephemeral=True)
                    return

                # Send summaries with period clarification
                period_text = "30 Days" if time_period.value == "30" else (
                    "7 Days" if time_period.value == "7" else "90 Days"
                )
                summary_message = f"**Energy Summary - Last {period_text}**\n"
                
                # Add additional warning in the summary for 7-day reports
                if time_period.value == "7":
                    summary_message += "\n⚠️ *Note: 7-day reports may be incomplete due to meter reading delays.*\n"
                
                for data in valid_results:
                    if data.consumption:
                        summary_message += f"\n**{data.fuel_type.capitalize()} Summary**\n```{data.summary}```\n"
                
                await interaction.followup.send(summary_message)

                # Send charts
                if energy_type.value == "both" and len(valid_results) > 1:
                    chart_buffer = generate_combined_chart(valid_results)
                    await interaction.followup.send(
                        file=discord.File(chart_buffer, "energy_consumption.png")
                    )
                else:
                    for data in valid_results:
                        chart_buffer = generate_chart(data)
                        await interaction.followup.send(
                            file=discord.File(chart_buffer, f"{data.fuel_type}_consumption.png")
                        )

        except ValueError as ve:
            await interaction.followup.send(f"❌ {str(ve)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error processing data: {str(e)}")
            await interaction.followup.send(
                "❌ An error occurred while processing your energy data. Please try again later.",
                ephemeral=True
            )

    except Exception as e:
        logger.error(f"Error in get_energy_data command: {str(e)}")
        await interaction.followup.send(
            "❌ An unexpected error occurred. Please try again later.",
            ephemeral=True
        )

    except Exception as e:
        logger.error(f"Error in get_energy_data command: {str(e)}")
        await interaction.followup.send(
            "❌ An unexpected error occurred. Please try again later.",
            ephemeral=True
        )

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_button(ctx):
    """Create a setup button in the current channel (Admin only)"""
    try:
        view = SetupView()
        message = await ctx.send(
            "🔋 Click the button below to set up your Octopus Energy account:",
            view=view
        )
        await message.pin()
        await ctx.send("✅ Setup button has been added and pinned!", ephemeral=True)
        logger.info(f"Setup button created in channel {ctx.channel.id} by {ctx.author.id}")
    except Exception as e:
        logger.error(f"Error creating setup button: {str(e)}")
        await ctx.send("❌ An error occurred while creating the setup button.", ephemeral=True)

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s) on startup")
    except Exception as e:
        logger.error(f"Error syncing commands: {str(e)}")

    # Set up the bot's status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="your energy usage 📊"
        )
    )

    # Add setup button in designated channel
    channel = bot.get_channel(SETUP_CHANNEL_ID)
    if channel:
        try:
            # Check for existing setup message
            async for message in channel.history(limit=100):
                if message.author == bot.user and "set up your Octopus Energy account" in message.content:
                    return
                    
            # Create new setup message if none exists
            view = SetupView()
            message = await channel.send(
                "🔋 Click the button below to set up your Octopus Energy account:",
                view=view
            )
            await message.pin()
            logger.info("Setup button created successfully")
        except Exception as e:
            logger.error(f"Error setting up button: {str(e)}")
    else:
        logger.warning(f"Setup channel {SETUP_CHANNEL_ID} not found")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            f"⏳ This command is on cooldown. Try again in {error.retry_after:.1f} seconds.",
            ephemeral=True
        )
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(
            "❌ You don't have permission to use this command.",
            ephemeral=True
        )
    else:
        logger.error(f"Command error: {str(error)}")
        await ctx.send(
            "❌ An error occurred while processing your command.",
            ephemeral=True
        )

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
