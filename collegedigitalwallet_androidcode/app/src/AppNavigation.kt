package com.example.collegedigitalwallet

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController

@Composable
fun AppNavigation() {
    val navController = rememberNavController()

    var walletRefreshKey by remember { mutableIntStateOf(0) }

    NavHost(
        navController = navController,
        startDestination = "login"
    ) {
        composable(route = "login") {
            LoginScreen(navController)
        }

        composable(route = "wallet") {
            WalletScreen(
                refreshKey = walletRefreshKey,
                onOnlineTap = { navController.navigate("pay_online") },
                onOfflineTap = { navController.navigate("pay_offline") },
                onLogout = {
                    navController.navigate("login") {
                        popUpTo("wallet") { inclusive = true }
                        launchSingleTop = true
                    }
                }
            )
        }

        composable(route = "pay_online") {
            OnlinePaymentScreen(
                navController = navController,
                onPaymentSuccess = {
                    walletRefreshKey++
                    navController.navigate("wallet") {
                        popUpTo("wallet") { inclusive = true }
                        launchSingleTop = true
                    }
                }
            )
        }

        composable(route = "pay_offline") {
            OfflinePaymentScreen(
                username = UserSession.username ?: "Ayudh",
                onQueued = {
                    walletRefreshKey++
                    navController.navigate("wallet") {
                        popUpTo("wallet") { inclusive = true }
                        launchSingleTop = true
                    }
                },
                onBack = {
                    navController.popBackStack()
                }
            )
        }
    }
}