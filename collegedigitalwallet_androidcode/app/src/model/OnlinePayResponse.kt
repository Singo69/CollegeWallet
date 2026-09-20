package com.example.collegedigitalwallet.model

data class OnlinePayResponse(
    val status: String,
    val message: String,
    val transaction_id: Int? = null,
    val sender: String? = null,
    val receiver: String? = null,
    val amount: Double? = null,
    val sender_new_balance: Double? = null,
    val receiver_new_balance: Double? = null
)
