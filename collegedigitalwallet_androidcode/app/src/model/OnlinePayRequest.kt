package com.example.collegedigitalwallet.model


data class OnlinePayRequest(
    val sender_username: String,
    val receiver_username: String,
    val amount: Double,
    val note: String? = null
)
