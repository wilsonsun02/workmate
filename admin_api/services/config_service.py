import json

from loguru import logger

from admin_api.models.init_db import get_db_connection


class ConfigService:
    @staticmethod
    def get_config(config_key: str, default_value=None):
        connection = get_db_connection()
        if not connection:
            return default_value

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT config_value FROM sys_configs WHERE config_key = %s",
                (config_key,),
            )
            result = cursor.fetchone()

            if result and result.get("config_value"):
                # config_value is stored as JSON string
                val = result["config_value"]
                if isinstance(val, str):
                    return json.loads(val)
                return val
            return default_value
        except Exception as e:
            logger.error("Error getting config {}: {}", config_key, e)
            return default_value
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def set_config(
        config_key: str, config_type: str, config_value: any, description: str = ""
    ):
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            # Serialize the value to JSON string before saving
            json_val = json.dumps(config_value)

            # Upsert logic (Insert on duplicate key update)
            cursor.execute(
                """
                INSERT INTO sys_configs (config_key, config_type, config_value, description)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                config_value = VALUES(config_value),
                description = IF(VALUES(description) != '', VALUES(description), description)
            """,
                (config_key, config_type, json_val, description),
            )

            connection.commit()
            return True
        except Exception as e:
            logger.error("Error setting config {}: {}", config_key, e)
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
